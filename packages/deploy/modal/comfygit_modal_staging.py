# pyright: reportAttributeAccessIssue=false, reportFunctionMemberAccess=false
"""Modal staging helper for the ComfyGit proxy-worker proof.

Run with:

    modal run packages/deploy/modal/comfygit_modal_staging.py

This is intentionally a deployment script, not imported package code. The
runtime image supplies CUDA/system dependencies; this script mounts a persistent
Modal volume, fetches development ComfyGit repos by explicit ref, materializes a
Git-backed environment, and can boot ComfyUI plus `cg serve --role proxy` for a
health check.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import modal


APP_NAME = "comfygit-proxy-proof-staging"
VOLUME_NAME = os.environ.get("COMFYGIT_MODAL_VOLUME_NAME", "comfygit-proxy-proof-v2")
VOLUME_VERSION = int(os.environ.get("COMFYGIT_MODAL_VOLUME_VERSION", "2"))
IMAGE_REF = "ghcr.io/akatz-ai/comfygit-runtime:cu126-egl-dev"
RUNTIME_DOCKERFILE = Path(__file__).with_name("runtime.Dockerfile")

DEFAULT_ENV_SOURCE = "https://github.com/akatz-ai/comfygit-testing-environment.git"
DEFAULT_ENV_BRANCH = "main"
DEFAULT_ENV_NAME = "modal-proxy-proof"
DEFAULT_COMFYGIT_REPO = "https://github.com/comfygit-ai/comfygit.git"
DEFAULT_MANAGER_REPO = "https://github.com/comfygit-ai/comfygit-manager.git"
DEFAULT_COMFYGIT_REF = "dev"
DEFAULT_MANAGER_REF = "dev"
DEFAULT_TORCH_BACKEND = "cu126"

VOLUME_ROOT = Path("/volume")
WORKSPACE_DIR = VOLUME_ROOT / "workspace"
MODELS_DIR = VOLUME_ROOT / "models"
REPOS_DIR = VOLUME_ROOT / "repos"
COMFYGIT_REPO_DIR = REPOS_DIR / "comfygit"
MANAGER_REPO_DIR = REPOS_DIR / "comfygit-manager"
TMP_UV_CACHE_DIR = Path("/tmp/comfygit-uv-cache")
VOLUME_UV_CACHE_DIR = WORKSPACE_DIR / "uv_cache"
RUNTIME_BUNDLE_DIR = VOLUME_ROOT / "runtime-bundles"
RUNTIME_BUNDLE_FORMAT = os.environ.get("COMFYGIT_MODAL_RUNTIME_BUNDLE_FORMAT", "tar-zst")
RUNTIME_ROOT = Path(os.environ.get("COMFYGIT_MODAL_RUNTIME_ROOT", "/tmp/comfygit-modal-runtime"))
RUNTIME_WORKSPACE_DIR = RUNTIME_ROOT / "workspace"
COMFY_PORT = 8290
PROXY_PORT = 8793
PROXY_TOKEN = "modal-proof-token"


app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True, version=VOLUME_VERSION)


def _modal_image() -> modal.Image:
    image_source = os.environ.get("COMFYGIT_MODAL_IMAGE_SOURCE", "registry").strip().lower()
    if image_source == "dockerfile":
        base = modal.Image.from_dockerfile(RUNTIME_DOCKERFILE, context_dir=RUNTIME_DOCKERFILE.parent)
    else:
        base = modal.Image.from_registry(os.environ.get("COMFYGIT_MODAL_IMAGE_REF", IMAGE_REF))
    env = {
        "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics,video",
        "COMFYGIT_HOME": str(WORKSPACE_DIR),
        "PYTHONUNBUFFERED": "1",
    }
    uv_link_mode = os.environ.get("COMFYGIT_MODAL_UV_LINK_MODE", "").strip()
    if uv_link_mode:
        env["UV_LINK_MODE"] = uv_link_mode
    return base.env(env)


image = _modal_image()


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
    print(f"+ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, timeout=timeout)


def _run_capture(cmd: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> str:
    print(f"+ {' '.join(cmd)}", flush=True)
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout.strip()
    if output:
        print(output, flush=True)
    return output


def _log_event(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def _remote_branch_exists(path: Path, ref: str) -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{ref}"],
        cwd=str(path),
        check=False,
        timeout=60,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _checkout_repo(url: str, ref: str, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        if path.exists():
            shutil.rmtree(path)
        _run(["git", "clone", url, str(path)], timeout=20 * 60)
    _run(["git", "fetch", "--all", "--tags", "--prune"], cwd=path, timeout=20 * 60)
    if _remote_branch_exists(path, ref):
        _run(["git", "checkout", "-B", ref, f"origin/{ref}"], cwd=path, timeout=5 * 60)
        _run(["git", "pull", "--ff-only"], cwd=path, timeout=10 * 60)
    else:
        _run(["git", "checkout", "--detach", ref], cwd=path, timeout=5 * 60)
    return _run_capture(["git", "rev-parse", "HEAD"], cwd=path, timeout=60)


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
    )


def _workspace_uv_cache_dir(mode: str) -> Path:
    normalized = mode.strip().lower()
    if normalized == "tmp":
        return TMP_UV_CACHE_DIR
    if normalized == "volume":
        return VOLUME_UV_CACHE_DIR
    raise ValueError(f"Unsupported uv cache mode: {mode!r}. Use 'tmp' or 'volume'.")


def _ensure_workspace_initialized() -> None:
    if not (WORKSPACE_DIR / ".metadata" / "workspace.json").exists():
        if WORKSPACE_DIR.exists():
            for child in WORKSPACE_DIR.iterdir():
                if child.name in {"uv_cache", "uv"}:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                else:
                    raise RuntimeError(
                        f"Workspace is not initialized but contains unexpected path: {child}"
                    )
        _run(["cg", "init", str(WORKSPACE_DIR), "--models-dir", str(MODELS_DIR), "--yes"], timeout=5 * 60)


def _configure_workspace_uv_cache(mode: str) -> Path:
    _ensure_workspace_initialized()
    uv_cache_dir = _workspace_uv_cache_dir(mode)
    uv_cache_dir.mkdir(parents=True, exist_ok=True)
    _run(["cg", "config", "--uv-cache", str(uv_cache_dir)], timeout=60)
    return uv_cache_dir


def _materialize_environment(
    *,
    source: str,
    branch: str,
    env_name: str,
    torch_backend: str,
    model_strategy: str,
    replace: bool,
) -> None:
    cmd = [
        "cg",
        "materialize",
        source,
        "--name",
        env_name,
        "--workspace",
        str(WORKSPACE_DIR),
        "--models-dir",
        str(MODELS_DIR),
        "--branch",
        branch,
        "--torch-backend",
        torch_backend,
        "--models",
        model_strategy,
        "--with-manager",
        "--use",
    ]
    if replace:
        cmd.append("--replace")
    _run(cmd, timeout=90 * 60)


def _write_local_overlay(env_name: str) -> None:
    overlay_path = WORKSPACE_DIR / "environments" / env_name / ".cec" / "overlays" / ".local.toml"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(
        "\n".join(
            [
                "[overlay]",
                'description = "Modal development sources"',
                'kind = "local"',
                "",
                "[sources]",
                f'comfygit-core = {{ path = "{COMFYGIT_REPO_DIR / "packages/core"}", editable = true }}',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _mark_manager_node_development(env_name: str) -> None:
    pyproject_path = WORKSPACE_DIR / "environments" / env_name / ".cec" / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"warning: {pyproject_path} does not exist; skipping manager dev node marker", flush=True)
        return

    content = pyproject_path.read_text(encoding="utf-8")
    section_match = re.search(
        r"(?m)^\[tool\.comfygit\.nodes\.comfygit-manager\]\n(?P<body>.*?)(?=^\[|\Z)",
        content,
        flags=re.DOTALL,
    )
    if section_match is None:
        print("warning: comfygit-manager is not tracked in pyproject.toml; skipping dev node marker", flush=True)
        return

    body = section_match.group("body")
    if re.search(r'(?m)^source\s*=\s*"development"\s*$', body):
        return

    if re.search(r"(?m)^source\s*=", body):
        new_body = re.sub(r'(?m)^source\s*=.*$', 'source = "development"', body, count=1)
    else:
        new_body = f'source = "development"\n{body}'

    updated = content[: section_match.start("body")] + new_body + content[section_match.end("body") :]
    pyproject_path.write_text(updated, encoding="utf-8")
    print("Marked comfygit-manager as a development node", flush=True)


def _install_dev_manager_symlink(env_name: str) -> None:
    env_dir = WORKSPACE_DIR / "environments" / env_name
    custom_nodes_dir = env_dir / "ComfyUI" / "custom_nodes"
    manager_target = custom_nodes_dir / "comfygit-manager"
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)

    if manager_target.exists() or manager_target.is_symlink():
        if manager_target.is_symlink() or manager_target.is_file():
            manager_target.unlink()
        else:
            shutil.rmtree(manager_target)
    manager_target.symlink_to(MANAGER_REPO_DIR, target_is_directory=True)
    _mark_manager_node_development(env_name)


def _apply_dev_sources(env_name: str) -> None:
    _write_local_overlay(env_name)
    _install_dev_manager_symlink(env_name)


def _sync_environment(env_name: str, torch_backend: str) -> None:
    _run(
        [
            "cg",
            "-e",
            env_name,
            "sync",
            "--torch-backend",
            torch_backend,
            "--verbose",
        ],
        timeout=90 * 60,
    )


def _runtime_bundle_path(env_name: str, bundle_format: str = RUNTIME_BUNDLE_FORMAT) -> Path:
    suffix_by_format = {
        "tar": ".tar",
        "tar-gz": ".tar.gz",
        "tar-zst": ".tar.zst",
    }
    try:
        suffix = suffix_by_format[bundle_format]
    except KeyError as exc:
        raise ValueError(f"Unsupported runtime bundle format: {bundle_format}") from exc
    return RUNTIME_BUNDLE_DIR / f"{env_name}{suffix}"


def _runtime_env(env_name: str, *, uv_cache_dir: Path = VOLUME_UV_CACHE_DIR) -> dict[str, str]:
    env_dir = RUNTIME_WORKSPACE_DIR / "environments" / env_name
    env = os.environ.copy()
    env.update(
        {
            "COMFYGIT_HOME": str(RUNTIME_WORKSPACE_DIR),
            "UV_PROJECT_ENVIRONMENT": str(env_dir / ".venv"),
            "UV_CACHE_DIR": str(uv_cache_dir),
            "UV_PYTHON_INSTALL_DIR": str(uv_cache_dir / "python"),
            "UV_LINK_MODE": "copy",
            "COMFYGIT_UV_LINK_MODE": "copy",
            "UV_TORCH_BACKEND": DEFAULT_TORCH_BACKEND,
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


def _hydrate_runtime_workspace(env_name: str) -> dict[str, object]:
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

    env_src = WORKSPACE_DIR / "environments" / env_name
    env_dst = RUNTIME_WORKSPACE_DIR / "environments" / env_name
    env_dst.parent.mkdir(parents=True, exist_ok=True)
    _copytree(env_src, env_dst, ignore={".venv"})

    cache_src = WORKSPACE_DIR / "comfygit_cache"
    cache_src.mkdir(parents=True, exist_ok=True)
    cache_link = RUNTIME_WORKSPACE_DIR / "comfygit_cache"
    if cache_link.exists() or cache_link.is_symlink():
        cache_link.unlink()
    cache_link.symlink_to(cache_src, target_is_directory=True)

    (RUNTIME_WORKSPACE_DIR / "input" / env_name).mkdir(parents=True, exist_ok=True)
    (RUNTIME_WORKSPACE_DIR / "output" / env_name).mkdir(parents=True, exist_ok=True)
    result = {
        "runtime_workspace": str(RUNTIME_WORKSPACE_DIR),
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("staging_runtime_hydrate_complete", **result)
    return result


def _sync_runtime_workspace(env_name: str, torch_backend: str) -> dict[str, object]:
    started = time.monotonic()
    env = _runtime_env(env_name, uv_cache_dir=VOLUME_UV_CACHE_DIR)
    env["UV_TORCH_BACKEND"] = torch_backend
    # Build the bundled venv at the exact absolute path used by runtime
    # containers. Python venv entrypoints are not safely relocatable.
    print(f"+ cg -e {env_name} sync --torch-backend {torch_backend} --verbose", flush=True)
    subprocess.run(
        ["cg", "-e", env_name, "sync", "--torch-backend", torch_backend, "--verbose"],
        check=True,
        timeout=90 * 60,
        env=env,
    )
    result = {
        "runtime_venv": str(RUNTIME_WORKSPACE_DIR / "environments" / env_name / ".venv"),
        "uv_cache": str(VOLUME_UV_CACHE_DIR),
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("staging_runtime_sync_complete", **result)
    return result


def _tar_create_args(bundle_path: Path, bundle_format: str) -> list[str]:
    if bundle_format == "tar":
        return ["tar", "-cf", str(bundle_path), "-C", str(RUNTIME_ROOT), "workspace"]
    if bundle_format == "tar-gz":
        return ["tar", "-czf", str(bundle_path), "-C", str(RUNTIME_ROOT), "workspace"]
    if bundle_format == "tar-zst":
        return [
            "tar",
            "--use-compress-program",
            "zstd -T0 -3",
            "-cf",
            str(bundle_path),
            "-C",
            str(RUNTIME_ROOT),
            "workspace",
        ]
    raise ValueError(f"Unsupported runtime bundle format: {bundle_format}")


def _build_runtime_bundle(
    env_name: str,
    torch_backend: str,
    *,
    bundle_format: str = RUNTIME_BUNDLE_FORMAT,
) -> dict[str, object]:
    started = time.monotonic()
    hydrate_info = _hydrate_runtime_workspace(env_name)
    sync_info = _sync_runtime_workspace(env_name, torch_backend)
    RUNTIME_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    bundle_path = _runtime_bundle_path(env_name, bundle_format)
    tmp_bundle_path = bundle_path.with_name(f".{bundle_path.name}.tmp")
    if tmp_bundle_path.exists():
        tmp_bundle_path.unlink()
    if bundle_path.exists():
        bundle_path.unlink()
    archive_started = time.monotonic()
    _run(_tar_create_args(tmp_bundle_path, bundle_format), timeout=90 * 60)
    tmp_bundle_path.replace(bundle_path)
    archive_seconds = time.monotonic() - archive_started
    size_bytes = bundle_path.stat().st_size
    result = {
        "bundle_path": str(bundle_path),
        "bundle_format": bundle_format,
        "size_bytes": size_bytes,
        "size_gib": round(size_bytes / 1024 / 1024 / 1024, 3),
        "hydrate": hydrate_info,
        "sync": sync_info,
        "archive_seconds": round(archive_seconds, 3),
        "seconds": round(time.monotonic() - started, 3),
    }
    _log_event("staging_runtime_bundle_complete", **result)
    return result


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


def _start_process(cmd: list[str], log_path: Path) -> subprocess.Popen:
    print(f"+ {' '.join(cmd)} > {log_path}", flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    return subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT)


def _probe_step(name: str, func) -> dict[str, object]:
    started = time.monotonic()
    try:
        detail = func()
        status = "ok"
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        status = "failed"
    return {
        "name": name,
        "status": status,
        "seconds": round(time.monotonic() - started, 3),
        "detail": detail,
    }


@app.function(
    image=image,
    volumes={"/volume": volume},
    timeout=20 * 60,
    startup_timeout=20 * 60,
)
def probe_volume_filesystem() -> dict[str, object]:
    """Probe Modal volume filesystem semantics that matter to ComfyGit/uv."""
    probe_dir = VOLUME_ROOT / "probes" / f"fs-{int(time.time())}"
    tmp_probe_dir = Path("/tmp") / f"comfygit-volume-probe-{int(time.time())}"
    shutil.rmtree(probe_dir, ignore_errors=True)
    shutil.rmtree(tmp_probe_dir, ignore_errors=True)
    probe_dir.mkdir(parents=True, exist_ok=True)
    tmp_probe_dir.mkdir(parents=True, exist_ok=True)

    volume_file = probe_dir / "file.txt"
    tmp_file = tmp_probe_dir / "file.txt"
    results: list[dict[str, object]] = []

    def write_file() -> str:
        volume_file.write_text("volume write\n", encoding="utf-8")
        return volume_file.read_text(encoding="utf-8").strip()

    def temp_named_file() -> str:
        with tempfile.NamedTemporaryFile("w", dir=probe_dir, delete=False, encoding="utf-8") as handle:
            handle.write("tempfile write\n")
            temp_path = Path(handle.name)
        return temp_path.read_text(encoding="utf-8").strip()

    def atomic_replace() -> str:
        source = probe_dir / ".tmp-replace"
        target = probe_dir / "replace-target.txt"
        source.write_text("replace\n", encoding="utf-8")
        os.replace(source, target)
        return target.read_text(encoding="utf-8").strip()

    def symlink_file() -> str:
        link = probe_dir / "file-link.txt"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(volume_file)
        return link.read_text(encoding="utf-8").strip()

    def symlink_dir() -> str:
        link = probe_dir / "dir-link"
        if link.exists() or link.is_symlink():
            if link.is_symlink() or link.is_file():
                link.unlink()
            else:
                shutil.rmtree(link)
        link.symlink_to(probe_dir, target_is_directory=True)
        return str(link.resolve())

    def hardlink_same_volume() -> str:
        link = probe_dir / "file-hardlink.txt"
        if link.exists():
            link.unlink()
        os.link(volume_file, link)
        return f"same_inode={volume_file.stat().st_ino == link.stat().st_ino}"

    def hardlink_tmp_to_volume() -> str:
        tmp_file.write_text("tmp write\n", encoding="utf-8")
        link = probe_dir / "tmp-hardlink.txt"
        if link.exists():
            link.unlink()
        os.link(tmp_file, link)
        return f"same_inode={tmp_file.stat().st_ino == link.stat().st_ino}"

    def hardlink_volume_to_tmp() -> str:
        link = tmp_probe_dir / "volume-hardlink.txt"
        if link.exists():
            link.unlink()
        os.link(volume_file, link)
        return f"same_inode={volume_file.stat().st_ino == link.stat().st_ino}"

    def uv_cache_on_volume() -> str:
        venv = probe_dir / "uv-volume-cache-venv"
        cache = probe_dir / "uv_cache"
        python_dir = probe_dir / "uv_python"
        _run(["uv", "venv", str(venv), "--python", "/usr/bin/python3.12"], timeout=5 * 60)
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(cache)
        env["UV_PYTHON_INSTALL_DIR"] = str(python_dir)
        print("+ UV_CACHE_DIR=<volume> uv pip install six==1.17.0", flush=True)
        subprocess.run(
            ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), "six==1.17.0"],
            check=True,
            timeout=5 * 60,
            env=env,
        )
        return "uv install ok"

    def uv_cache_on_tmp() -> str:
        venv = probe_dir / "uv-tmp-cache-venv"
        cache = tmp_probe_dir / "uv_cache"
        python_dir = tmp_probe_dir / "uv_python"
        _run(["uv", "venv", str(venv), "--python", "/usr/bin/python3.12"], timeout=5 * 60)
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(cache)
        env["UV_PYTHON_INSTALL_DIR"] = str(python_dir)
        print("+ UV_CACHE_DIR=<tmp> uv pip install six==1.17.0", flush=True)
        subprocess.run(
            ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), "six==1.17.0"],
            check=True,
            timeout=5 * 60,
            env=env,
        )
        return "uv install ok"

    for name, func in [
        ("write_file", write_file),
        ("temp_named_file", temp_named_file),
        ("atomic_replace", atomic_replace),
        ("symlink_file", symlink_file),
        ("symlink_dir", symlink_dir),
        ("hardlink_same_volume", hardlink_same_volume),
        ("hardlink_tmp_to_volume", hardlink_tmp_to_volume),
        ("hardlink_volume_to_tmp", hardlink_volume_to_tmp),
        ("uv_cache_on_volume", uv_cache_on_volume),
        ("uv_cache_on_tmp", uv_cache_on_tmp),
    ]:
        results.append(_probe_step(name, func))

    volume.commit()
    return {
        "probe_dir": str(probe_dir),
        "tmp_probe_dir": str(tmp_probe_dir),
        "results": results,
    }


@app.function(
    image=image,
    gpu="T4",
    volumes={"/volume": volume},
    secrets=[modal.Secret.from_name("comfygit-download-secrets")],
    timeout=3 * 60 * 60,
    startup_timeout=20 * 60,
)
def stage_environment(
    source: str = DEFAULT_ENV_SOURCE,
    branch: str = DEFAULT_ENV_BRANCH,
    env_name: str = DEFAULT_ENV_NAME,
    comfygit_ref: str = DEFAULT_COMFYGIT_REF,
    manager_ref: str = DEFAULT_MANAGER_REF,
    torch_backend: str = DEFAULT_TORCH_BACKEND,
    model_strategy: str = "all",
    uv_cache: str = "volume",
    replace: bool = False,
    materialize: bool = True,
    sync_environment: bool = True,
    build_runtime_bundle: bool = False,
    runtime_bundle_format: str = RUNTIME_BUNDLE_FORMAT,
    boot_proxy: bool = True,
) -> dict[str, object]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    comfygit_sha = _checkout_repo(DEFAULT_COMFYGIT_REPO, comfygit_ref, COMFYGIT_REPO_DIR)
    manager_sha = _checkout_repo(DEFAULT_MANAGER_REPO, manager_ref, MANAGER_REPO_DIR)
    _install_dev_cli()
    uv_cache_dir = _configure_workspace_uv_cache(uv_cache)
    if materialize:
        _materialize_environment(
            source=source,
            branch=branch,
            env_name=env_name,
            torch_backend=torch_backend,
            model_strategy=model_strategy,
            replace=replace,
        )
    _apply_dev_sources(env_name)
    if sync_environment:
        _sync_environment(env_name, torch_backend)
    bundle_info: dict[str, object] | None = None
    if build_runtime_bundle:
        bundle_info = _build_runtime_bundle(
            env_name,
            torch_backend,
            bundle_format=runtime_bundle_format,
        )
    volume.commit()

    result: dict[str, object] = {
        "volume": VOLUME_NAME,
        "volume_version": str(VOLUME_VERSION),
        "workspace": str(WORKSPACE_DIR),
        "models": str(MODELS_DIR),
        "environment": env_name,
        "comfygit_sha": comfygit_sha,
        "manager_sha": manager_sha,
        "uv_cache": str(uv_cache_dir),
        "materialize": materialize,
        "sync_environment": sync_environment,
        "runtime_bundle": bundle_info,
        "boot_proxy": boot_proxy,
    }

    if not boot_proxy:
        return result

    logs_dir = VOLUME_ROOT / "logs" / env_name
    comfy = _start_process(
        [
            "cg",
            "-e",
            env_name,
            "run",
            "--listen",
            "127.0.0.1",
            "--port",
            str(COMFY_PORT),
            "--torch-backend",
            torch_backend,
            "--disable-auto-launch",
            "--disable-metadata",
        ],
        logs_dir / "comfyui.log",
    )
    try:
        _wait_http(f"http://127.0.0.1:{COMFY_PORT}/system_stats", timeout=10 * 60)
        proxy = _start_process(
            [
                "cg",
                "-e",
                env_name,
                "serve",
                "--role",
                "proxy",
                "--host",
                "127.0.0.1",
                "--port",
                str(PROXY_PORT),
                "--comfy-url",
                f"http://127.0.0.1:{COMFY_PORT}",
                "--proxy-token",
                PROXY_TOKEN,
            ],
            logs_dir / "proxy.log",
        )
        try:
            _wait_http(
                f"http://127.0.0.1:{PROXY_PORT}/proxy/health",
                timeout=2 * 60,
                headers={"Authorization": f"Bearer {PROXY_TOKEN}"},
            )
            result["proxy_health"] = "ok"
        finally:
            proxy.terminate()
            try:
                proxy.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proxy.kill()
    finally:
        comfy.terminate()
        try:
            comfy.wait(timeout=15)
        except subprocess.TimeoutExpired:
            comfy.kill()

    return result


@app.local_entrypoint()
def main(
    source: str = DEFAULT_ENV_SOURCE,
    branch: str = DEFAULT_ENV_BRANCH,
    env_name: str = DEFAULT_ENV_NAME,
    comfygit_ref: str = DEFAULT_COMFYGIT_REF,
    manager_ref: str = DEFAULT_MANAGER_REF,
    torch_backend: str = DEFAULT_TORCH_BACKEND,
    model_strategy: str = "all",
    uv_cache: str = "volume",
    replace: bool = False,
    materialize: bool = True,
    sync_environment: bool = True,
    build_runtime_bundle: bool = False,
    runtime_bundle_format: str = RUNTIME_BUNDLE_FORMAT,
    boot_proxy: bool = True,
    probe_fs: bool = False,
) -> None:
    if probe_fs:
        print(json.dumps(probe_volume_filesystem.remote(), indent=2, sort_keys=True))
        return

    print(
        stage_environment.remote(
            source=source,
            branch=branch,
            env_name=env_name,
            comfygit_ref=comfygit_ref,
            manager_ref=manager_ref,
            torch_backend=torch_backend,
            model_strategy=model_strategy,
            uv_cache=uv_cache,
            replace=replace,
            materialize=materialize,
            sync_environment=sync_environment,
            build_runtime_bundle=build_runtime_bundle,
            runtime_bundle_format=runtime_bundle_format,
            boot_proxy=boot_proxy,
        )
    )
