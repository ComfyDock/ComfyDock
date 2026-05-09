# pyright: reportAttributeAccessIssue=false, reportFunctionMemberAccess=false
"""Modal runtime web endpoint for an already-materialized ComfyGit environment.

This is the production-facing half of the Modal proof:

1. `comfygit_modal_staging.py` materializes a Git-backed environment into a
   persistent Modal Volume.
2. This script starts ComfyUI and `cg serve --role proxy` from that volume and
   exposes the proxy over a Modal web endpoint.

Deploy with:

    COMFYGIT_MODAL_IMAGE_SOURCE=dockerfile modal deploy \
      packages/deploy/modal/comfygit_modal_proxy_runtime.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import modal


APP_NAME = os.environ.get("COMFYGIT_MODAL_RUNTIME_APP_NAME", "comfygit-proxy-proof-runtime")
VOLUME_NAME = os.environ.get("COMFYGIT_MODAL_VOLUME_NAME", "comfygit-proxy-proof-v2")
VOLUME_VERSION = int(os.environ.get("COMFYGIT_MODAL_VOLUME_VERSION", "2"))
IMAGE_REF = "ghcr.io/akatz-ai/comfygit-runtime:cu126-egl-dev"
RUNTIME_DOCKERFILE = Path(__file__).with_name("runtime.Dockerfile")

ENV_NAME = os.environ.get("COMFYGIT_MODAL_ENV_NAME", "modal-proxy-proof")
TORCH_BACKEND = os.environ.get("COMFYGIT_MODAL_TORCH_BACKEND", "cu126")
GPU_TYPE = os.environ.get("COMFYGIT_MODAL_GPU", "T4")
ENABLE_MEMORY_SNAPSHOT = os.environ.get("COMFYGIT_MODAL_ENABLE_MEMORY_SNAPSHOT", "").lower() in {
    "1",
    "true",
    "yes",
}
ENABLE_GPU_SNAPSHOT = os.environ.get("COMFYGIT_MODAL_ENABLE_GPU_SNAPSHOT", "").lower() in {
    "1",
    "true",
    "yes",
}
SCALEDOWN_WINDOW = int(os.environ.get("COMFYGIT_MODAL_SCALEDOWN_WINDOW", "60"))
MAX_CONTAINERS = int(os.environ.get("COMFYGIT_MODAL_MAX_CONTAINERS", "1"))
MIN_CONTAINERS = int(os.environ.get("COMFYGIT_MODAL_MIN_CONTAINERS", "0"))
BUFFER_CONTAINERS = int(os.environ.get("COMFYGIT_MODAL_BUFFER_CONTAINERS", "0"))
STARTUP_TIMEOUT = int(os.environ.get("COMFYGIT_MODAL_STARTUP_TIMEOUT", str(60 * 60)))
COMFY_STARTUP_TIMEOUT = int(os.environ.get("COMFYGIT_MODAL_COMFY_STARTUP_TIMEOUT", str(60 * 60)))
BOOT_IN_ENTER = os.environ.get("COMFYGIT_MODAL_BOOT_IN_ENTER", "").lower() in {
    "1",
    "true",
    "yes",
} or ENABLE_MEMORY_SNAPSHOT

VOLUME_ROOT = Path("/volume")
WORKSPACE_DIR = VOLUME_ROOT / "workspace"
MODELS_DIR = VOLUME_ROOT / "models"
REPOS_DIR = VOLUME_ROOT / "repos"
COMFYGIT_REPO_DIR = REPOS_DIR / "comfygit"
VOLUME_UV_CACHE_DIR = WORKSPACE_DIR / "uv_cache"
RUNTIME_BUNDLE_DIR = VOLUME_ROOT / "runtime-bundles"
RUNTIME_BUNDLE_FORMAT = os.environ.get("COMFYGIT_MODAL_RUNTIME_BUNDLE_FORMAT", "tar-zst")
RUNTIME_ROOT = Path(os.environ.get("COMFYGIT_MODAL_RUNTIME_ROOT", "/tmp/comfygit-modal-runtime"))
RUNTIME_WORKSPACE_DIR = RUNTIME_ROOT / "workspace"
RUNTIME_ENV_DIR = RUNTIME_WORKSPACE_DIR / "environments" / ENV_NAME
RUNTIME_LOGS_DIR = RUNTIME_ROOT / "logs"
RUNTIME_MODE = os.environ.get("COMFYGIT_MODAL_RUNTIME_MODE", "volume-cache").strip().lower()
RUNTIME_SYNC_ON_START = os.environ.get("COMFYGIT_MODAL_RUNTIME_SYNC_ON_START", "1").lower() in {
    "1",
    "true",
    "yes",
}
INSTALL_DEV_CLI_ON_START = os.environ.get("COMFYGIT_MODAL_INSTALL_DEV_CLI_ON_START", "").lower() in {
    "1",
    "true",
    "yes",
}
COMFY_PORT = 8290
PROXY_PORT = 8793
PROXY_TOKEN = os.environ.get("COMFYGIT_MODAL_PROXY_TOKEN", "modal-proof-token")
PROXY_LABEL = os.environ.get(
    "COMFYGIT_MODAL_PROXY_LABEL",
    "proxy-snapshot" if ENABLE_MEMORY_SNAPSHOT else "proxy",
)


app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=False, version=VOLUME_VERSION)


def _modal_image() -> modal.Image:
    image_source = os.environ.get("COMFYGIT_MODAL_IMAGE_SOURCE", "registry").strip().lower()
    if image_source == "dockerfile":
        base = modal.Image.from_dockerfile(RUNTIME_DOCKERFILE, context_dir=RUNTIME_DOCKERFILE.parent)
    else:
        base = modal.Image.from_registry(os.environ.get("COMFYGIT_MODAL_IMAGE_REF", IMAGE_REF))

    env = {
        "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics,video",
        "COMFYGIT_HOME": str(RUNTIME_WORKSPACE_DIR),
        "COMFYGIT_MODAL_RUNTIME_APP_NAME": APP_NAME,
        "COMFYGIT_MODAL_ENV_NAME": ENV_NAME,
        "COMFYGIT_MODAL_GPU": GPU_TYPE,
        "COMFYGIT_MODAL_PROXY_TOKEN": PROXY_TOKEN,
        "COMFYGIT_MODAL_PROXY_LABEL": PROXY_LABEL,
        "COMFYGIT_MODAL_VOLUME_NAME": VOLUME_NAME,
        "COMFYGIT_MODAL_VOLUME_VERSION": str(VOLUME_VERSION),
        "COMFYGIT_MODAL_ENABLE_GPU_SNAPSHOT": "1" if ENABLE_GPU_SNAPSHOT else "0",
        "COMFYGIT_MODAL_ENABLE_MEMORY_SNAPSHOT": "1" if ENABLE_MEMORY_SNAPSHOT else "0",
        "COMFYGIT_MODAL_BOOT_IN_ENTER": "1" if BOOT_IN_ENTER else "0",
        "COMFYGIT_MODAL_INSTALL_DEV_CLI_ON_START": "1" if INSTALL_DEV_CLI_ON_START else "0",
        "COMFYGIT_MODAL_RUNTIME_BUNDLE_FORMAT": RUNTIME_BUNDLE_FORMAT,
        "COMFYGIT_MODAL_RUNTIME_MODE": RUNTIME_MODE,
        "COMFYGIT_MODAL_RUNTIME_ROOT": str(RUNTIME_ROOT),
        "COMFYGIT_MODAL_RUNTIME_SYNC_ON_START": "1" if RUNTIME_SYNC_ON_START else "0",
        "COMFYGIT_MODAL_TORCH_BACKEND": TORCH_BACKEND,
        "PYTHONUNBUFFERED": "1",
    }
    uv_link_mode = os.environ.get("COMFYGIT_MODAL_UV_LINK_MODE", "").strip()
    if uv_link_mode:
        env["UV_LINK_MODE"] = uv_link_mode
    return base.env(env)


image = _modal_image()
api_image = image.uv_pip_install("fastapi[standard]")
job_index = modal.Dict.from_name(f"{APP_NAME}-jobs", create_if_missing=True)


def _log_event(event: str, **fields: Any) -> None:
    print({"event": event, **fields}, flush=True)


def _run(cmd: list[str], *, timeout: int | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, timeout=timeout, env=env)


def _wait_http(url: str, *, timeout: int, headers: dict[str, str] | None = None) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= response.status < 500:
                    print(f"health ok: {url} status={response.status}", flush=True)
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 60,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {data}") from exc


def _request_multipart_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any],
    uploads: list[dict[str, Any]],
    timeout: float = 60,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body, content_type = _encode_multipart(payload, uploads)
    request_headers = dict(headers or {})
    request_headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {data}") from exc


def _encode_multipart(payload: dict[str, Any], uploads: list[dict[str, Any]]) -> tuple[bytes, str]:
    boundary = f"----comfygit-modal-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add(value: str | bytes) -> None:
        chunks.append(value if isinstance(value, bytes) else value.encode("utf-8"))

    add(f"--{boundary}\r\n")
    add('Content-Disposition: form-data; name="payload"\r\n')
    add("Content-Type: application/json\r\n\r\n")
    add(json.dumps(payload))
    add("\r\n")

    for index, upload in enumerate(uploads):
        field_name = str(upload.get("field_name") or f"file_{index}")
        filename = str(upload.get("filename") or f"{field_name}.bin")
        content_type = str(upload.get("content_type") or "application/octet-stream")
        body = upload.get("body") or b""
        if not isinstance(body, bytes):
            raise TypeError(f"Upload {field_name} body must be bytes.")
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n')
        add(f"Content-Type: {content_type}\r\n\r\n")
        add(body)
        add("\r\n")

    add(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _request_bytes(
    url: str,
    *,
    timeout: float = 60,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("content-type", "application/octet-stream")


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _job_key(value: str) -> str:
    return f"job:{value}"


def _prompt_key(value: str) -> str:
    return f"prompt:{value}"


def _job_put(key: str, value: dict[str, Any]) -> None:
    try:
        job_index.put(key, value)
    except Exception as exc:
        _log_event("modal_job_index_put_failed", key=key, error=str(exc))


def _job_get(key: str) -> dict[str, Any] | None:
    try:
        value = job_index.get(key)
    except Exception as exc:
        _log_event("modal_job_index_get_failed", key=key, error=str(exc))
        return None
    return dict(value) if isinstance(value, dict) else None


def _resolve_modal_job(identifier: str) -> tuple[str, dict[str, Any] | None]:
    prompt_mapping = _job_get(_prompt_key(identifier))
    if prompt_mapping and isinstance(prompt_mapping.get("modal_call_id"), str):
        call_id = str(prompt_mapping["modal_call_id"])
        return call_id, _job_get(_job_key(call_id))
    job = _job_get(_job_key(identifier))
    return identifier, job


def _proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_TOKEN}"}


def _callback_target_from_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    callback = payload.get("callback")
    if not isinstance(callback, dict):
        return None
    run_id = callback.get("run_id")
    url = callback.get("url")
    if not isinstance(run_id, str) or not run_id or not isinstance(url, str) or not url:
        return None
    result = {"run_id": run_id, "url": url}
    token = callback.get("token")
    if isinstance(token, str) and token:
        result["token"] = token
    return result


def _post_callback_error(payload: dict[str, Any], error_payload: dict[str, Any]) -> None:
    callback = _callback_target_from_payload(payload)
    if callback is None:
        return
    body = {"run_id": callback["run_id"], **error_payload}
    headers: dict[str, str] = {}
    if callback.get("token"):
        headers["Authorization"] = f"Bearer {callback['token']}"
    try:
        _request_json("POST", callback["url"], payload=body, headers=headers, timeout=30)
    except Exception as exc:
        _log_event("modal_worker_error_callback_failed", error=str(exc), callback_url=callback["url"])


def _start_process(
    cmd: list[str],
    log_path: Path,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    print(f"+ {' '.join(cmd)} > {log_path}", flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    def _pump_output() -> None:
        if process.stdout is None:
            return
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            for line in process.stdout:
                handle.write(line)
                handle.flush()
                print(line.rstrip("\n"), flush=True)

    threading.Thread(target=_pump_output, daemon=True).start()
    return process


def _install_dev_cli() -> dict[str, Any]:
    started = time.monotonic()
    existing_cg = shutil.which("cg")
    if existing_cg and not INSTALL_DEV_CLI_ON_START:
        result = {
            "skipped": True,
            "reason": "image-baked-cg",
            "cg": existing_cg,
            "seconds": round(time.monotonic() - started, 3),
        }
        _log_event("runtime_dev_cli_install_skipped", **result)
        return result

    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            "/opt/venv/bin/python",
            "-e",
            str(COMFYGIT_REPO_DIR / "packages/core"),
            "-e",
            str(COMFYGIT_REPO_DIR / "packages/cli"),
        ],
        timeout=30 * 60,
        env=_runtime_env(),
    )
    result = {
        "skipped": False,
        "reason": "volume-editable-install",
        "cg": shutil.which("cg"),
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("runtime_dev_cli_install_complete", **result)
    return result


def _assert_materialized_environment() -> None:
    env_dir = WORKSPACE_DIR / "environments" / ENV_NAME
    required_paths = [
        WORKSPACE_DIR / ".metadata" / "workspace.json",
        env_dir / "ComfyUI",
        env_dir / ".cec" / "pyproject.toml",
        VOLUME_UV_CACHE_DIR,
    ]
    if INSTALL_DEV_CLI_ON_START or not shutil.which("cg"):
        required_paths.extend(
            [
                COMFYGIT_REPO_DIR / "packages/core",
                COMFYGIT_REPO_DIR / "packages/cli",
            ]
        )
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise RuntimeError(
            "Modal volume is not materialized for runtime use. Missing: "
            + ", ".join(missing)
        )


def _runtime_bundle_path() -> Path:
    suffix_by_format = {
        "tar": ".tar",
        "tar-gz": ".tar.gz",
        "tar-zst": ".tar.zst",
    }
    try:
        suffix = suffix_by_format[RUNTIME_BUNDLE_FORMAT]
    except KeyError as exc:
        raise ValueError(f"Unsupported runtime bundle format: {RUNTIME_BUNDLE_FORMAT}") from exc
    return RUNTIME_BUNDLE_DIR / f"{ENV_NAME}{suffix}"


def _runtime_cache_dir() -> Path:
    if RUNTIME_MODE == "copy-cache":
        return RUNTIME_ROOT / "uv_cache"
    if RUNTIME_MODE == "fresh-cache":
        return RUNTIME_ROOT / "uv_cache"
    return VOLUME_UV_CACHE_DIR


def _runtime_env() -> dict[str, str]:
    uv_cache_dir = _runtime_cache_dir()
    env = os.environ.copy()
    env.update(
        {
            "COMFYGIT_HOME": str(RUNTIME_WORKSPACE_DIR),
            "UV_PROJECT_ENVIRONMENT": str(RUNTIME_ENV_DIR / ".venv"),
            "UV_CACHE_DIR": str(uv_cache_dir),
            "UV_PYTHON_INSTALL_DIR": str(uv_cache_dir / "python"),
            "UV_LINK_MODE": "copy",
            "COMFYGIT_UV_LINK_MODE": "copy",
            "UV_TORCH_BACKEND": TORCH_BACKEND,
            "UV_NO_PROGRESS": "1",
            "NO_COLOR": "1",
            "PYTHONUNBUFFERED": "1",
            "VIRTUAL_ENV": "",
        }
    )
    return env


def _copytree(src: Path, dst: Path, *, ignore: set[str] | None = None) -> None:
    if not src.exists():
        return
    ignored = ignore or set()
    shutil.copytree(
        src,
        dst,
        symlinks=True,
        ignore=lambda _directory, names: sorted(ignored.intersection(names)),
    )


def _hydrate_runtime_workspace() -> dict[str, Any]:
    started = time.monotonic()
    if RUNTIME_WORKSPACE_DIR.exists():
        shutil.rmtree(RUNTIME_WORKSPACE_DIR)

    RUNTIME_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    _copytree(WORKSPACE_DIR / ".metadata", RUNTIME_WORKSPACE_DIR / ".metadata")

    config_path = RUNTIME_WORKSPACE_DIR / ".metadata" / "workspace.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["external_uv_cache"] = str(VOLUME_UV_CACHE_DIR)
    config["global_model_directory"] = {
        "path": str(MODELS_DIR),
        "added_at": config.get("global_model_directory", {}).get("added_at", ""),
        "last_sync": config.get("global_model_directory", {}).get("last_sync", ""),
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    env_src = WORKSPACE_DIR / "environments" / ENV_NAME
    env_dst = RUNTIME_ENV_DIR
    env_dst.parent.mkdir(parents=True, exist_ok=True)
    _copytree(env_src, env_dst, ignore={".venv"})

    cache_src = WORKSPACE_DIR / "comfygit_cache"
    cache_src.mkdir(parents=True, exist_ok=True)
    cache_link = RUNTIME_WORKSPACE_DIR / "comfygit_cache"
    if cache_link.exists() or cache_link.is_symlink():
        cache_link.unlink()
    cache_link.symlink_to(cache_src, target_is_directory=True)

    (RUNTIME_WORKSPACE_DIR / "input" / ENV_NAME).mkdir(parents=True, exist_ok=True)
    (RUNTIME_WORKSPACE_DIR / "output" / ENV_NAME).mkdir(parents=True, exist_ok=True)

    result = {
        "runtime_workspace": str(RUNTIME_WORKSPACE_DIR),
        "runtime_environment": str(env_dst),
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("runtime_hydrate_complete", **result)
    return result


def _copy_runtime_cache() -> dict[str, Any]:
    started = time.monotonic()
    if RUNTIME_MODE not in {"copy-cache", "fresh-cache"}:
        return {"skipped": True, "seconds": 0, "uv_cache": str(VOLUME_UV_CACHE_DIR)}

    local_cache = _runtime_cache_dir()
    if local_cache.exists():
        shutil.rmtree(local_cache)
    if RUNTIME_MODE == "copy-cache":
        shutil.copytree(VOLUME_UV_CACHE_DIR, local_cache, symlinks=True)
    else:
        local_cache.mkdir(parents=True, exist_ok=True)
    result = {
        "skipped": False,
        "uv_cache": str(local_cache),
        "mode": RUNTIME_MODE,
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("runtime_cache_prepare_complete", **result)
    return result


def _tar_extract_args(bundle_path: Path) -> list[str]:
    if RUNTIME_BUNDLE_FORMAT == "tar":
        return ["tar", "-xf", str(bundle_path), "-C", str(RUNTIME_ROOT)]
    if RUNTIME_BUNDLE_FORMAT == "tar-gz":
        return ["tar", "-xzf", str(bundle_path), "-C", str(RUNTIME_ROOT)]
    if RUNTIME_BUNDLE_FORMAT == "tar-zst":
        return [
            "tar",
            "--use-compress-program",
            "zstd -d -T0",
            "-xf",
            str(bundle_path),
            "-C",
            str(RUNTIME_ROOT),
        ]
    raise ValueError(f"Unsupported runtime bundle format: {RUNTIME_BUNDLE_FORMAT}")


def _extract_runtime_bundle() -> dict[str, Any]:
    started = time.monotonic()
    bundle_path = _runtime_bundle_path()
    if not bundle_path.exists():
        raise RuntimeError(f"Runtime bundle does not exist: {bundle_path}")
    if RUNTIME_WORKSPACE_DIR.exists():
        shutil.rmtree(RUNTIME_WORKSPACE_DIR)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    _run(_tar_extract_args(bundle_path), timeout=90 * 60)
    result = {
        "bundle_path": str(bundle_path),
        "bundle_format": RUNTIME_BUNDLE_FORMAT,
        "size_bytes": bundle_path.stat().st_size,
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("runtime_bundle_extract_complete", **result)
    return result


def _prepare_runtime_files() -> dict[str, Any]:
    started = time.monotonic()
    if RUNTIME_MODE == "runtime-bundle":
        bundle_info = _extract_runtime_bundle()
        sync_info = {
            "skipped": True,
            "reason": "runtime-bundle",
            "runtime_venv": str(RUNTIME_ENV_DIR / ".venv"),
            "seconds": 0,
        }
        result = {
            "mode": RUNTIME_MODE,
            "bundle": bundle_info,
            "sync": sync_info,
            "seconds": round(time.monotonic() - started, 3),
        }
        _log_event("runtime_prepare_files_complete", **result)
        return result

    hydrate_info = _hydrate_runtime_workspace()
    cache_info = _copy_runtime_cache()
    sync_info = _sync_runtime_environment()
    result = {
        "mode": RUNTIME_MODE,
        "hydrate": hydrate_info,
        "cache": cache_info,
        "sync": sync_info,
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("runtime_prepare_files_complete", **result)
    return result


def _sync_runtime_environment() -> dict[str, Any]:
    if not RUNTIME_SYNC_ON_START:
        result = {
            "skipped": True,
            "runtime_venv": str(RUNTIME_ENV_DIR / ".venv"),
            "seconds": 0,
        }
        _log_event("runtime_sync_skipped", **result)
        return result

    started = time.monotonic()
    _run(
        [
            "cg",
            "-e",
            ENV_NAME,
            "sync",
            "--torch-backend",
            TORCH_BACKEND,
            "--verbose",
        ],
        timeout=90 * 60,
        env=_runtime_env(),
    )
    result = {
        "skipped": False,
        "runtime_venv": str(RUNTIME_ENV_DIR / ".venv"),
        "uv_cache": str(_runtime_cache_dir()),
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("runtime_sync_complete", **result)
    return result


def _txt2img_prompt() -> dict[str, Any]:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(time.time() * 1000) % 1_000_000_000,
                "steps": 12,
                "cfg": 8,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "v1-5-pruned-emaonly-fp16.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "beautiful scenery nature glass bottle landscape, purple galaxy bottle",
                "clip": ["4", 1],
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "text, watermark", "clip": ["4", 1]},
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyGit_Modal_Profile", "images": ["8", 0]},
        },
    }


@app.cls(
    image=image,
    gpu=GPU_TYPE,
    volumes={"/volume": volume},
    secrets=[modal.Secret.from_name("comfygit-download-secrets")],
    timeout=3 * 60 * 60,
    startup_timeout=STARTUP_TIMEOUT,
    min_containers=MIN_CONTAINERS,
    buffer_containers=BUFFER_CONTAINERS,
    scaledown_window=SCALEDOWN_WINDOW,
    max_containers=MAX_CONTAINERS,
    enable_memory_snapshot=ENABLE_MEMORY_SNAPSHOT,
    experimental_options={"enable_gpu_snapshot": True} if ENABLE_GPU_SNAPSHOT else None,
)
class ProxyRuntime:
    @modal.enter(snap=ENABLE_MEMORY_SNAPSHOT)
    def prepare(self) -> None:
        started = time.monotonic()
        volume.reload()
        _assert_materialized_environment()
        install_info = _install_dev_cli()
        install_seconds = time.monotonic() - started
        files_info = _prepare_runtime_files()
        ready: dict[str, Any] | None = None
        if BOOT_IN_ENTER:
            ready = self._ensure_started()
        _log_event(
            "runtime_prepare_complete",
            seconds=round(time.monotonic() - started, 3),
            install_seconds=round(install_seconds, 3),
            install=install_info,
            files=files_info,
            runtime_mode=RUNTIME_MODE,
            boot_in_enter=BOOT_IN_ENTER,
            memory_snapshot=ENABLE_MEMORY_SNAPSHOT,
            gpu_snapshot=ENABLE_GPU_SNAPSHOT,
            ready=ready,
        )

    def _ensure_started(self) -> dict[str, Any]:
        existing = getattr(self, "_ready_info", None)
        if isinstance(existing, dict):
            return existing

        started = time.monotonic()
        if not RUNTIME_ENV_DIR.exists():
            _assert_materialized_environment()
            _prepare_runtime_files()
        logs_dir = RUNTIME_LOGS_DIR / ENV_NAME
        runtime_env = _runtime_env()
        comfy = _start_process(
            [
                "cg",
                "-e",
                ENV_NAME,
                "run",
                "--no-sync",
                "--listen",
                "127.0.0.1",
                "--port",
                str(COMFY_PORT),
                "--torch-backend",
                TORCH_BACKEND,
                "--disable-auto-launch",
                "--disable-metadata",
            ],
            logs_dir / "comfyui.log",
            env=runtime_env,
        )
        self._comfy_process = comfy
        try:
            _wait_http(f"http://127.0.0.1:{COMFY_PORT}/system_stats", timeout=COMFY_STARTUP_TIMEOUT)
            comfy_ready_seconds = time.monotonic() - started
            proxy = _start_process(
                [
                    "cg",
                    "-e",
                    ENV_NAME,
                    "serve",
                    "--role",
                    "proxy",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(PROXY_PORT),
                    "--comfy-url",
                    f"http://127.0.0.1:{COMFY_PORT}",
                    "--proxy-token",
                    PROXY_TOKEN,
                ],
                logs_dir / "proxy.log",
                env=runtime_env,
            )
            self._proxy_process = proxy
            _wait_http(
                f"http://127.0.0.1:{PROXY_PORT}/proxy/health",
                timeout=2 * 60,
                headers={"Authorization": f"Bearer {PROXY_TOKEN}"},
            )
            ready_info = {
                "event": "runtime_proxy_ready",
                "seconds": round(time.monotonic() - started, 3),
                "comfy_ready_seconds": round(comfy_ready_seconds, 3),
                "memory_snapshot": ENABLE_MEMORY_SNAPSHOT,
                "gpu_snapshot": ENABLE_GPU_SNAPSHOT,
                "proxy_port": PROXY_PORT,
                "comfy_port": COMFY_PORT,
            }
            self._ready_info = ready_info
            print(
                ready_info,
                flush=True,
            )
            return ready_info
        except Exception:
            comfy.terminate()
            try:
                comfy.wait(timeout=15)
            except subprocess.TimeoutExpired:
                comfy.kill()
            raise

    @modal.web_server(PROXY_PORT, startup_timeout=STARTUP_TIMEOUT, label=f"{PROXY_LABEL}-direct")
    def serve(self) -> None:
        self._ensure_started()

    @modal.method()
    def ready(self) -> dict[str, Any]:
        return self._ensure_started()

    @modal.method()
    def run_generation(
        self,
        payload: dict[str, Any],
        uploads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        call_id = modal.current_function_call_id() or uuid.uuid4().hex
        uploads = uploads or []
        started = time.monotonic()
        timeout_seconds = float(payload.get("timeout_seconds") or 3 * 60 * 60)
        poll_interval_seconds = float(payload.get("poll_interval_seconds") or 1)
        base_url = f"http://127.0.0.1:{PROXY_PORT}"
        headers = _proxy_headers()

        _job_put(
            _job_key(call_id),
            {
                "status": "starting",
                "modal_call_id": call_id,
                "updated_at": _utc_timestamp(),
            },
        )
        try:
            ready_info = self._ensure_started()
            submit_started = time.monotonic()
            if uploads:
                submitted = _request_multipart_json(
                    "POST",
                    f"{base_url}/proxy/runs",
                    payload=payload,
                    uploads=uploads,
                    headers=headers,
                    timeout=max(60, timeout_seconds),
                )
            else:
                submitted = _request_json(
                    "POST",
                    f"{base_url}/proxy/runs",
                    payload=payload,
                    headers=headers,
                    timeout=max(60, timeout_seconds),
                )
            prompt_id = str(submitted.get("prompt_id") or "")
            if not prompt_id:
                raise RuntimeError(f"Proxy did not return prompt_id: {submitted}")

            _job_put(
                _job_key(call_id),
                {
                    "status": str(submitted.get("status") or "submitted"),
                    "modal_call_id": call_id,
                    "prompt_id": prompt_id,
                    "submitted": submitted,
                    "ready": ready_info,
                    "submit_seconds": round(time.monotonic() - submit_started, 3),
                    "updated_at": _utc_timestamp(),
                },
            )
            _job_put(
                _prompt_key(prompt_id),
                {
                    "modal_call_id": call_id,
                    "prompt_id": prompt_id,
                    "updated_at": _utc_timestamp(),
                },
            )

            deadline = time.monotonic() + timeout_seconds
            completed: dict[str, Any] = {}
            while time.monotonic() < deadline:
                completed = _request_json(
                    "GET",
                    f"{base_url}/proxy/runs/{urllib.parse.quote(prompt_id, safe='')}",
                    headers=headers,
                    timeout=60,
                )
                status = str(completed.get("status") or "").lower()
                _job_put(
                    _job_key(call_id),
                    {
                        "status": status or "running",
                        "modal_call_id": call_id,
                        "prompt_id": prompt_id,
                        "result": completed,
                        "updated_at": _utc_timestamp(),
                    },
                )
                if status in {"completed", "error", "failed", "timeout", "cancelled"}:
                    result = {
                        "modal_call_id": call_id,
                        "prompt_id": prompt_id,
                        "seconds": round(time.monotonic() - started, 3),
                        **completed,
                    }
                    _job_put(_job_key(call_id), {**result, "updated_at": _utc_timestamp()})
                    return result
                time.sleep(max(0.1, poll_interval_seconds))

            error_payload = {
                "status": "timeout",
                "error": "timeout",
                "message": f"Timed out waiting for proxy prompt {prompt_id}",
                "prompt_id": prompt_id,
                "modal_call_id": call_id,
            }
            _job_put(_job_key(call_id), {**error_payload, "updated_at": _utc_timestamp()})
            _post_callback_error(payload, error_payload)
            return error_payload
        except Exception as exc:
            error_payload = {
                "status": "error",
                "error": "modal_worker_error",
                "message": str(exc),
                "modal_call_id": call_id,
            }
            _job_put(_job_key(call_id), {**error_payload, "updated_at": _utc_timestamp()})
            _post_callback_error(payload, error_payload)
            raise

    @modal.method()
    def profile_txt2img(self, timeout_seconds: float = 30 * 60) -> dict[str, Any]:
        timings: dict[str, float] = {}
        started = time.monotonic()
        ready_info = self._ensure_started()
        timings["ready_seconds"] = time.monotonic() - started

        headers = {"Authorization": f"Bearer {PROXY_TOKEN}"}
        base_url = f"http://127.0.0.1:{PROXY_PORT}"
        health_started = time.monotonic()
        health = _request_json("GET", f"{base_url}/proxy/health", headers=headers, timeout=60)
        timings["health_seconds"] = time.monotonic() - health_started

        payload = {
            "prompt": _txt2img_prompt(),
            "outputs": [{"name": "save_image", "type": "image", "node_id": "9", "selector": "primary"}],
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": 1,
        }
        submit_started = time.monotonic()
        submitted = _request_json(
            "POST",
            f"{base_url}/proxy/runs",
            payload=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        timings["submit_seconds"] = time.monotonic() - submit_started
        prompt_id = str(submitted.get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError(f"Proxy did not return prompt_id: {submitted}")

        poll_started = time.monotonic()
        completed: dict[str, Any] = {}
        while time.monotonic() - poll_started < timeout_seconds:
            completed = _request_json(
                "GET",
                f"{base_url}/proxy/runs/{urllib.parse.quote(prompt_id)}",
                headers=headers,
                timeout=60,
            )
            status = str(completed.get("status") or "").lower()
            if status == "completed":
                break
            if status in {"error", "failed", "cancelled"}:
                raise RuntimeError(f"Run ended with status {status}: {completed}")
            time.sleep(1)
        else:
            raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")
        timings["completion_poll_seconds"] = time.monotonic() - poll_started

        artifacts = [
            artifact
            for output in completed.get("outputs", [])
            if isinstance(output, dict)
            for artifact in output.get("artifacts", [])
            if isinstance(artifact, dict)
        ]
        if not artifacts:
            raise RuntimeError(f"Completed run had no artifacts: {completed}")

        artifact = artifacts[0]
        artifact_url = str(artifact.get("url") or "")
        if artifact_url.startswith("/"):
            artifact_url = f"{base_url}{artifact_url}"

        download_started = time.monotonic()
        artifact_bytes, content_type = _request_bytes(
            artifact_url,
            headers=headers,
            timeout=timeout_seconds,
        )
        timings["artifact_download_seconds"] = time.monotonic() - download_started
        timings["total_seconds"] = time.monotonic() - started

        return {
            "ready": ready_info,
            "health": health,
            "submitted": submitted,
            "completed": completed,
            "artifact": {
                "bytes": len(artifact_bytes),
                "content_type": content_type,
                "metadata": artifact,
            },
            "timings": {key: round(value, 3) for key, value in timings.items()},
        }


@app.function(image=api_image, timeout=60 * 60, scaledown_window=SCALEDOWN_WINDOW)
@modal.asgi_app(label=PROXY_LABEL)
def proxy_api():
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    api = FastAPI()

    def unauthorized() -> JSONResponse:
        return JSONResponse(
            {"error": "forbidden", "message": "Proxy token is invalid."},
            status_code=403,
        )

    def auth_response(request: Request) -> JSONResponse | None:
        expected = f"Bearer {PROXY_TOKEN}"
        if request.headers.get("Authorization", "") == expected:
            return None
        return unauthorized()

    async def job_put(key: str, value: dict[str, Any]) -> None:
        await job_index.put.aio(key, value)

    async def job_get(key: str) -> dict[str, Any] | None:
        value = await job_index.get.aio(key)
        return value if isinstance(value, dict) else None

    async def resolve_modal_job(prompt_id: str) -> tuple[str, dict[str, Any] | None]:
        direct = await job_get(_job_key(prompt_id))
        if direct is not None:
            return str(direct.get("modal_call_id") or prompt_id), direct
        prompt_mapping = await job_get(_prompt_key(prompt_id))
        if prompt_mapping is not None:
            call_id = str(prompt_mapping.get("modal_call_id") or prompt_id)
            return call_id, await job_get(_job_key(call_id))
        return prompt_id, None

    async def read_proxy_request(request: Request) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        content_type = request.headers.get("content-type", "").lower()
        if not content_type.startswith("multipart/"):
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Proxy run payload must be a JSON object.")
            return payload, []

        form = await request.form()
        payload_part = form.get("payload")
        if not isinstance(payload_part, str):
            raise ValueError("Multipart proxy request must include a JSON payload field.")
        payload_data = json.loads(payload_part)
        if not isinstance(payload_data, dict):
            raise ValueError("Multipart proxy payload must be a JSON object.")

        uploads: list[dict[str, Any]] = []
        for field_name, value in form.multi_items():
            if field_name == "payload":
                continue
            filename = getattr(value, "filename", None)
            read = getattr(value, "read", None)
            if not filename or not callable(read):
                continue
            body = await read()
            uploads.append(
                {
                    "field_name": str(field_name),
                    "filename": str(filename),
                    "content_type": str(getattr(value, "content_type", None) or "application/octet-stream"),
                    "body": body,
                }
            )
        return payload_data, uploads

    async def proxy_health(request):
        if response := auth_response(request):
            return response
        return {
            "status": "ok",
            "role": "modal-job-proxy",
            "runtime": "modal",
            "environment": ENV_NAME,
            "gpu": GPU_TYPE,
            "worker": "ProxyRuntime.run_generation",
        }

    proxy_health.__annotations__["request"] = Request
    api.add_api_route("/proxy/health", proxy_health, methods=["GET"])

    async def proxy_submit(request):
        if response := auth_response(request):
            return response
        try:
            payload, uploads = await read_proxy_request(request)
        except Exception as exc:
            return JSONResponse({"error": "bad_request", "message": str(exc)}, status_code=400)

        call = await ProxyRuntime().run_generation.spawn.aio(payload, uploads)
        call_id = str(call.object_id)
        submitted = {
            "status": "submitted",
            "prompt_id": call_id,
            "modal_call_id": call_id,
            "runtime": "modal-job",
        }
        await job_put(
            _job_key(call_id),
            {
                **submitted,
                "updated_at": _utc_timestamp(),
            },
        )
        return submitted

    proxy_submit.__annotations__["request"] = Request
    api.add_api_route("/proxy/runs", proxy_submit, methods=["POST"])

    async def proxy_status(request, prompt_id):
        if response := auth_response(request):
            return response
        call_id, job = await resolve_modal_job(prompt_id)
        if job is not None:
            result = job.get("result")
            payload: dict[str, Any] = {
                "status": str(job.get("status") or "running"),
                "prompt_id": str(job.get("prompt_id") or prompt_id),
                "modal_call_id": call_id,
            }
            if isinstance(result, dict):
                payload.update(result)
                payload["modal_call_id"] = call_id
            return payload

        try:
            result = await modal.FunctionCall.from_id(call_id).get.aio(timeout=0)
        except modal.exception.TimeoutError:
            return {"status": "running", "prompt_id": prompt_id, "modal_call_id": call_id}
        except Exception as exc:
            return JSONResponse(
                {
                    "error": "not_found",
                    "message": f"Unknown proxy run: {exc}",
                    "prompt_id": prompt_id,
                    "modal_call_id": call_id,
                },
                status_code=404,
            )
        if isinstance(result, dict):
            await job_put(_job_key(call_id), {**result, "updated_at": _utc_timestamp()})
            return result
        return {"status": "completed", "prompt_id": prompt_id, "modal_call_id": call_id}

    proxy_status.__annotations__["request"] = Request
    proxy_status.__annotations__["prompt_id"] = str
    api.add_api_route("/proxy/runs/{prompt_id}", proxy_status, methods=["GET"])

    async def proxy_cancel(request, prompt_id):
        if response := auth_response(request):
            return response
        call_id, job = await resolve_modal_job(prompt_id)
        warning = None
        try:
            await modal.FunctionCall.from_id(call_id).cancel.aio(terminate_containers=True)
        except Exception as exc:
            warning = str(exc)
        result = {
            "status": "cancelled",
            "prompt_id": str(job.get("prompt_id") if job else prompt_id),
            "modal_call_id": call_id,
        }
        if warning:
            result["warning"] = warning
        await job_put(_job_key(call_id), {**result, "updated_at": _utc_timestamp()})
        await job_put(_prompt_key(prompt_id), {"modal_call_id": call_id, **result, "updated_at": _utc_timestamp()})
        return result

    proxy_cancel.__annotations__["request"] = Request
    proxy_cancel.__annotations__["prompt_id"] = str
    api.add_api_route("/proxy/runs/{prompt_id}/cancel", proxy_cancel, methods=["POST"])

    return api
