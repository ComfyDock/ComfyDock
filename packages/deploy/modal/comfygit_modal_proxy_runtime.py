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
RUNTIME_ROOT = Path(os.environ.get("COMFYGIT_MODAL_RUNTIME_ROOT", "/tmp/comfygit-modal-runtime"))
RUNTIME_WORKSPACE_DIR = RUNTIME_ROOT / "workspace"
RUNTIME_ENV_DIR = RUNTIME_WORKSPACE_DIR / "environments" / ENV_NAME
RUNTIME_LOGS_DIR = RUNTIME_ROOT / "logs"
RUNTIME_SYNC_ON_START = os.environ.get("COMFYGIT_MODAL_RUNTIME_SYNC_ON_START", "1").lower() in {
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
        "PYTHONUNBUFFERED": "1",
    }
    uv_link_mode = os.environ.get("COMFYGIT_MODAL_UV_LINK_MODE", "").strip()
    if uv_link_mode:
        env["UV_LINK_MODE"] = uv_link_mode
    return base.env(env)


image = _modal_image()


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


def _request_bytes(
    url: str,
    *,
    timeout: float = 60,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("content-type", "application/octet-stream")


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


def _install_dev_cli() -> None:
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


def _assert_materialized_environment() -> None:
    env_dir = WORKSPACE_DIR / "environments" / ENV_NAME
    required_paths = [
        WORKSPACE_DIR / ".metadata" / "workspace.json",
        COMFYGIT_REPO_DIR / "packages/core",
        COMFYGIT_REPO_DIR / "packages/cli",
        env_dir / "ComfyUI",
        env_dir / ".cec" / "pyproject.toml",
        VOLUME_UV_CACHE_DIR,
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise RuntimeError(
            "Modal volume is not materialized for runtime use. Missing: "
            + ", ".join(missing)
        )


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "COMFYGIT_HOME": str(RUNTIME_WORKSPACE_DIR),
            "UV_PROJECT_ENVIRONMENT": str(RUNTIME_ENV_DIR / ".venv"),
            "UV_CACHE_DIR": str(VOLUME_UV_CACHE_DIR),
            "UV_PYTHON_INSTALL_DIR": str(VOLUME_UV_CACHE_DIR / "python"),
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
        "uv_cache": str(VOLUME_UV_CACHE_DIR),
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
        _install_dev_cli()
        install_seconds = time.monotonic() - started
        hydrate_info = _hydrate_runtime_workspace()
        sync_info = _sync_runtime_environment()
        ready: dict[str, Any] | None = None
        if BOOT_IN_ENTER:
            ready = self._ensure_started()
        _log_event(
            "runtime_prepare_complete",
            seconds=round(time.monotonic() - started, 3),
            install_seconds=round(install_seconds, 3),
            hydrate=hydrate_info,
            sync=sync_info,
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
            _hydrate_runtime_workspace()
            _sync_runtime_environment()
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

    @modal.web_server(PROXY_PORT, startup_timeout=STARTUP_TIMEOUT, label=PROXY_LABEL)
    def serve(self) -> None:
        self._ensure_started()

    @modal.method()
    def ready(self) -> dict[str, Any]:
        return self._ensure_started()

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
