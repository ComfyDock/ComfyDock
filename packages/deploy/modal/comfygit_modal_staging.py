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

import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import modal


APP_NAME = "comfygit-proxy-proof-staging"
VOLUME_NAME = "comfygit-proxy-proof"
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
UV_CACHE_DIR = Path("/tmp/comfygit-uv-cache")
COMFY_PORT = 8290
PROXY_PORT = 8793


app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _modal_image() -> modal.Image:
    image_source = os.environ.get("COMFYGIT_MODAL_IMAGE_SOURCE", "registry").strip().lower()
    if image_source == "dockerfile":
        base = modal.Image.from_dockerfile(RUNTIME_DOCKERFILE, context_dir=RUNTIME_DOCKERFILE.parent)
    else:
        base = modal.Image.from_registry(os.environ.get("COMFYGIT_MODAL_IMAGE_REF", IMAGE_REF))
    return base.env(
        {
            "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics,video",
            "COMFYGIT_HOME": str(WORKSPACE_DIR),
            "PYTHONUNBUFFERED": "1",
        }
    )


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


def _configure_workspace_uv_cache() -> None:
    UV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not (WORKSPACE_DIR / ".metadata" / "workspace.json").exists():
        _run(["cg", "init", str(WORKSPACE_DIR), "--models-dir", str(MODELS_DIR), "--yes"], timeout=5 * 60)
    _run(["cg", "config", "--uv-cache", str(UV_CACHE_DIR)], timeout=60)


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


def _install_dev_manager(env_name: str) -> None:
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

    env_python = env_dir / ".venv" / "bin" / "python"
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(env_python),
            "-e",
            str(COMFYGIT_REPO_DIR / "packages/core"),
        ],
        timeout=30 * 60,
    )


def _wait_http(url: str, *, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
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
    replace: bool = False,
    boot_proxy: bool = True,
) -> dict[str, str | bool]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    comfygit_sha = _checkout_repo(DEFAULT_COMFYGIT_REPO, comfygit_ref, COMFYGIT_REPO_DIR)
    manager_sha = _checkout_repo(DEFAULT_MANAGER_REPO, manager_ref, MANAGER_REPO_DIR)
    _install_dev_cli()
    _configure_workspace_uv_cache()
    _materialize_environment(
        source=source,
        branch=branch,
        env_name=env_name,
        torch_backend=torch_backend,
        model_strategy=model_strategy,
        replace=replace,
    )
    _write_local_overlay(env_name)
    _install_dev_manager(env_name)
    volume.commit()

    result: dict[str, str | bool] = {
        "workspace": str(WORKSPACE_DIR),
        "models": str(MODELS_DIR),
        "environment": env_name,
        "comfygit_sha": comfygit_sha,
        "manager_sha": manager_sha,
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
                "modal-proof-token",
            ],
            logs_dir / "proxy.log",
        )
        try:
            _wait_http(f"http://127.0.0.1:{PROXY_PORT}/proxy/health", timeout=2 * 60)
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
    replace: bool = False,
    boot_proxy: bool = True,
) -> None:
    print(
        stage_environment.remote(
            source=source,
            branch=branch,
            env_name=env_name,
            comfygit_ref=comfygit_ref,
            manager_ref=manager_ref,
            replace=replace,
            boot_proxy=boot_proxy,
        )
    )
