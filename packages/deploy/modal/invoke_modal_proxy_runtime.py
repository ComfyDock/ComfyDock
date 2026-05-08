# pyright: reportAttributeAccessIssue=false
"""Invoke deployed Modal proxy runtime methods without going through HTTP startup.

Use this for cold-start profiling. The Modal method call waits for container
startup and ComfyUI boot under the deployed function timeout, so a local HTTP
client timeout does not accidentally create a new cold-start attempt.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import modal


DEFAULT_APP_NAME = "comfygit-proxy-proof-runtime"


def _runtime(app_name: str) -> Any:
    runtime_cls = modal.Cls.from_name(app_name, "ProxyRuntime")
    return runtime_cls()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument("--action", choices=["ready", "profile"], default="ready")
    parser.add_argument("--timeout-seconds", type=float, default=30 * 60)
    args = parser.parse_args()

    runtime = _runtime(args.app_name)
    if args.action == "ready":
        result = runtime.ready.remote()
    else:
        result = runtime.profile_txt2img.remote(timeout_seconds=args.timeout_seconds)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
