#!/usr/bin/env python3
"""Probe a Modal-like runtime hydration flow in a local container.

The persistent workspace is treated like a remote volume: it owns models and
dependency caches. The runtime workspace is disposable local disk: it owns the
active ComfyUI tree, custom nodes, local venv, logs, and temp outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _log(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    verbose: bool = False,
) -> subprocess.CompletedProcess[str]:
    _log("command_start", cmd=cmd, cwd=str(cwd) if cwd else None)
    started = time.monotonic()
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        timeout=timeout,
        text=True,
        stdout=None if verbose else subprocess.PIPE,
        stderr=None if verbose else subprocess.STDOUT,
        check=False,
    )
    seconds = time.monotonic() - started
    _log("command_done", cmd=cmd, returncode=completed.returncode, seconds=round(seconds, 3))
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr)
        raise RuntimeError(f"Command failed with {completed.returncode}: {' '.join(cmd)}")
    return completed


def _wait_http(url: str, *, timeout: int, headers: dict[str, str] | None = None) -> None:
    started = time.monotonic()
    deadline = started + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= response.status < 500:
                    _log("http_ready", url=url, status=response.status, seconds=round(time.monotonic() - started, 3))
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _load_workspace_config(workspace: Path) -> dict[str, Any]:
    return json.loads((workspace / ".metadata" / "workspace.json").read_text(encoding="utf-8"))


def _active_environment(workspace: Path) -> str:
    config = _load_workspace_config(workspace)
    env_name = str(config.get("active_environment") or "").strip()
    if not env_name:
        raise RuntimeError(f"No active environment in {workspace / '.metadata' / 'workspace.json'}")
    return env_name


def _copytree(src: Path, dst: Path, *, ignore: set[str] | None = None) -> None:
    ignore = ignore or set()
    if not src.exists():
        return
    shutil.copytree(
        src,
        dst,
        symlinks=True,
        ignore=lambda _directory, names: sorted(ignore.intersection(names)),
    )


def _hydrate_workspace(
    *,
    persistent_workspace: Path,
    runtime_workspace: Path,
    env_name: str,
    uv_cache: Path,
    models_dir: Path,
) -> tuple[Path, Path]:
    started = time.monotonic()
    if runtime_workspace.exists():
        shutil.rmtree(runtime_workspace)

    runtime_workspace.mkdir(parents=True)
    _copytree(persistent_workspace / ".metadata", runtime_workspace / ".metadata")

    config_path = runtime_workspace / ".metadata" / "workspace.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["external_uv_cache"] = str(uv_cache)
    config["global_model_directory"] = {
        "path": str(models_dir),
        "added_at": config.get("global_model_directory", {}).get("added_at", ""),
        "last_sync": config.get("global_model_directory", {}).get("last_sync", ""),
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    env_src = persistent_workspace / "environments" / env_name
    env_dst = runtime_workspace / "environments" / env_name
    env_dst.parent.mkdir(parents=True)
    _copytree(env_src, env_dst, ignore={".venv"})

    # Keep ComfyGit caches persistent while the runnable environment stays local.
    cache_link = runtime_workspace / "comfygit_cache"
    if cache_link.exists() or cache_link.is_symlink():
        cache_link.unlink()
    cache_link.symlink_to(persistent_workspace / "comfygit_cache", target_is_directory=True)

    # Runtime input/output are disposable for this probe; proxy workers upload
    # artifacts back to the coordinator in the real architecture.
    (runtime_workspace / "input" / env_name).mkdir(parents=True, exist_ok=True)
    (runtime_workspace / "output" / env_name).mkdir(parents=True, exist_ok=True)
    _log(
        "hydrate_done",
        seconds=round(time.monotonic() - started, 3),
        runtime_workspace=str(runtime_workspace),
        runtime_environment=str(env_dst),
    )
    return runtime_workspace, env_dst


def _bundle_path(args: argparse.Namespace) -> Path:
    suffix_by_format = {
        "tar": ".tar",
        "tar-gz": ".tar.gz",
        "tar-zst": ".tar.zst",
    }
    suffix = suffix_by_format.get(args.bundle_format)
    if suffix is None:
        raise RuntimeError(f"Unsupported bundle format: {args.bundle_format}")
    return Path(args.runtime_root) / f"{args.environment}{suffix}"


def _tar_create_args(bundle_path: Path, args: argparse.Namespace) -> list[str]:
    runtime_root = Path(args.runtime_root)
    if args.bundle_format == "tar":
        return ["tar", "-cf", str(bundle_path), "-C", str(runtime_root), "workspace"]
    if args.bundle_format == "tar-gz":
        return ["tar", "-czf", str(bundle_path), "-C", str(runtime_root), "workspace"]
    if args.bundle_format == "tar-zst":
        return [
            "tar",
            "--use-compress-program",
            "zstd -T0 -3",
            "-cf",
            str(bundle_path),
            "-C",
            str(runtime_root),
            "workspace",
        ]
    raise RuntimeError(f"Unsupported bundle format: {args.bundle_format}")


def _tar_extract_args(bundle_path: Path, args: argparse.Namespace) -> list[str]:
    runtime_root = Path(args.runtime_root)
    if args.bundle_format == "tar":
        return ["tar", "-xf", str(bundle_path), "-C", str(runtime_root)]
    if args.bundle_format == "tar-gz":
        return ["tar", "-xzf", str(bundle_path), "-C", str(runtime_root)]
    if args.bundle_format == "tar-zst":
        return [
            "tar",
            "--use-compress-program",
            "zstd -d -T0",
            "-xf",
            str(bundle_path),
            "-C",
            str(runtime_root),
        ]
    raise RuntimeError(f"Unsupported bundle format: {args.bundle_format}")


def _create_runtime_bundle(args: argparse.Namespace) -> Path:
    bundle_path = _bundle_path(args)
    tmp_path = bundle_path.with_name(f".{bundle_path.name}.tmp")
    for path in [tmp_path, bundle_path]:
        if path.exists():
            path.unlink()
    started = time.monotonic()
    _run(_tar_create_args(tmp_path, args), timeout=args.bundle_timeout)
    tmp_path.replace(bundle_path)
    _log(
        "bundle_created",
        bundle=str(bundle_path),
        bundle_format=args.bundle_format,
        size_bytes=bundle_path.stat().st_size,
        seconds=round(time.monotonic() - started, 3),
    )
    return bundle_path


def _extract_runtime_bundle(args: argparse.Namespace, runtime_workspace: Path) -> None:
    bundle_path = Path(args.bundle).resolve() if args.bundle else _bundle_path(args)
    if not bundle_path.exists():
        raise RuntimeError(f"Runtime bundle does not exist: {bundle_path}")
    if runtime_workspace.exists():
        shutil.rmtree(runtime_workspace)
    Path(args.runtime_root).mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    _run(_tar_extract_args(bundle_path, args), timeout=args.bundle_timeout)
    _log(
        "bundle_extracted",
        bundle=str(bundle_path),
        bundle_format=args.bundle_format,
        size_bytes=bundle_path.stat().st_size,
        seconds=round(time.monotonic() - started, 3),
    )


def _sync_local_venv(
    *,
    runtime_workspace: Path,
    env_name: str,
    env_dir: Path,
    uv_cache: Path,
    python_install_dir: Path,
    torch_backend: str,
    timeout: int,
) -> None:
    started = time.monotonic()
    env = os.environ.copy()
    env.update(
        {
            "UV_PROJECT_ENVIRONMENT": str(env_dir / ".venv"),
            "UV_CACHE_DIR": str(uv_cache),
            "UV_PYTHON_INSTALL_DIR": str(python_install_dir),
            "UV_LINK_MODE": "copy",
            "COMFYGIT_UV_LINK_MODE": "copy",
            "COMFYGIT_HOME": str(runtime_workspace),
            "UV_TORCH_BACKEND": torch_backend,
            "UV_NO_PROGRESS": "1",
            "NO_COLOR": "1",
            "VIRTUAL_ENV": "",
        }
    )
    _run(
        ["cg", "-e", env_name, "sync", "--torch-backend", torch_backend, "--verbose"],
        env=env,
        timeout=timeout,
        verbose=True,
    )
    _log("venv_sync_done", seconds=round(time.monotonic() - started, 3), venv=str(env_dir / ".venv"))


def _copy_cache_for_mode(args: argparse.Namespace, uv_cache: Path) -> Path:
    if args.mode == "volume-cache":
        return uv_cache
    local_cache = Path(args.runtime_root) / "uv_cache"
    started = time.monotonic()
    if local_cache.exists():
        shutil.rmtree(local_cache)
    if args.mode == "copy-cache":
        shutil.copytree(uv_cache, local_cache, symlinks=True)
    elif args.mode == "fresh-cache":
        local_cache.mkdir(parents=True, exist_ok=True)
    else:
        raise RuntimeError(f"Unsupported cache mode: {args.mode}")
    _log(
        "cache_ready",
        mode=args.mode,
        uv_cache=str(local_cache),
        seconds=round(time.monotonic() - started, 3),
    )
    return local_cache


def _start_process(cmd: list[str], *, log_path: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    _log("process_start", cmd=cmd, log=str(log_path))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8", errors="replace")
    return subprocess.Popen(
        cmd,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        start_new_session=True,
    )


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)


def _boot_runtime(args: argparse.Namespace, runtime_workspace: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "COMFYGIT_HOME": str(runtime_workspace),
            "PYTHONUNBUFFERED": "1",
        }
    )
    logs_dir = Path(args.runtime_root) / "logs"
    comfy: subprocess.Popen[str] | None = None
    proxy: subprocess.Popen[str] | None = None
    started = time.monotonic()
    try:
        comfy = _start_process(
            [
                "cg",
                "-e",
                args.environment,
                "run",
                "--no-sync",
                "--listen",
                "127.0.0.1",
                "--port",
                str(args.comfy_port),
                "--torch-backend",
                args.torch_backend,
                "--disable-auto-launch",
                "--disable-metadata",
            ],
            log_path=logs_dir / "comfyui.log",
            env=env,
        )
        _wait_http(f"http://127.0.0.1:{args.comfy_port}/system_stats", timeout=args.startup_timeout)
        comfy_seconds = time.monotonic() - started
        if args.proxy:
            proxy = _start_process(
                [
                    "cg",
                    "-e",
                    args.environment,
                    "serve",
                    "--role",
                    "proxy",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.proxy_port),
                    "--comfy-url",
                    f"http://127.0.0.1:{args.comfy_port}",
                    "--proxy-token",
                    args.proxy_token,
                ],
                log_path=logs_dir / "proxy.log",
                env=env,
            )
            _wait_http(
                f"http://127.0.0.1:{args.proxy_port}/proxy/health",
                timeout=120,
                headers={"Authorization": f"Bearer {args.proxy_token}"},
            )
        _log(
            "runtime_ready",
            seconds=round(time.monotonic() - started, 3),
            comfy_ready_seconds=round(comfy_seconds, 3),
            comfy_port=args.comfy_port,
            proxy_port=args.proxy_port if args.proxy else None,
            logs=str(logs_dir),
        )
        if args.keep_running:
            _log("keep_running", message="Press Ctrl-C to stop")
            while True:
                time.sleep(60)
    finally:
        if not args.keep_running:
            _stop_process(proxy)
            _stop_process(comfy)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persistent-workspace", type=Path, default=Path(os.environ.get("COMFYGIT_HOME", "")))
    parser.add_argument("--environment", default="")
    parser.add_argument("--runtime-root", type=Path, default=Path("/tmp/comfygit-runtime-hydration-probe"))
    parser.add_argument(
        "--mode",
        choices=["volume-cache", "copy-cache", "fresh-cache", "runtime-bundle"],
        default="volume-cache",
    )
    parser.add_argument("--uv-cache", type=Path)
    parser.add_argument("--models-dir", type=Path, default=Path(os.environ.get("SHARED_MODELS_DIR", "/data/models")))
    parser.add_argument("--python-install-dir", type=Path)
    parser.add_argument("--torch-backend", default=os.environ.get("COMFYGIT_TORCH_BACKEND", "cu126"))
    parser.add_argument("--comfy-port", type=int, default=8390)
    parser.add_argument("--proxy-port", type=int, default=8893)
    parser.add_argument("--proxy-token", default="local-hydration-probe-token")
    parser.add_argument("--startup-timeout", type=int, default=600)
    parser.add_argument("--sync-timeout", type=int, default=1800)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--bundle-format", choices=["tar", "tar-gz", "tar-zst"], default="tar-gz")
    parser.add_argument("--bundle-timeout", type=int, default=3600)
    parser.add_argument("--create-bundle", action="store_true")
    parser.add_argument("--no-proxy", dest="proxy", action="store_false")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    parser.set_defaults(proxy=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    persistent_workspace = args.persistent_workspace.resolve()
    if not persistent_workspace.exists():
        raise RuntimeError(f"Persistent workspace does not exist: {persistent_workspace}")
    if not args.environment:
        args.environment = _active_environment(persistent_workspace)
    uv_cache = (args.uv_cache or (persistent_workspace / "uv_cache")).resolve()
    python_install_dir = (args.python_install_dir or (uv_cache / "python")).resolve()
    runtime_workspace = args.runtime_root / "workspace"

    _log(
        "probe_start",
        mode=args.mode,
        persistent_workspace=str(persistent_workspace),
        runtime_workspace=str(runtime_workspace),
        environment=args.environment,
        uv_cache=str(uv_cache),
        models_dir=str(args.models_dir),
    )
    if args.mode == "runtime-bundle":
        _extract_runtime_bundle(args, runtime_workspace)
    else:
        _, env_dir = _hydrate_workspace(
            persistent_workspace=persistent_workspace,
            runtime_workspace=runtime_workspace,
            env_name=args.environment,
            uv_cache=uv_cache,
            models_dir=args.models_dir.resolve(),
        )
        local_uv_cache = _copy_cache_for_mode(args, uv_cache)
        local_python_install_dir = local_uv_cache / "python"
        if not args.skip_sync:
            _sync_local_venv(
                runtime_workspace=runtime_workspace,
                env_name=args.environment,
                env_dir=env_dir,
                uv_cache=local_uv_cache,
                python_install_dir=local_python_install_dir,
                torch_backend=args.torch_backend,
                timeout=args.sync_timeout,
            )
        if args.create_bundle:
            _create_runtime_bundle(args)
    _boot_runtime(args, runtime_workspace)


if __name__ == "__main__":
    main()
