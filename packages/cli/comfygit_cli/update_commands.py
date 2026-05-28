"""Self-update command for the ComfyGit CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from shutil import which

from .utils import update_checker

_RELEASES_URL = "https://github.com/comfygit-ai/comfygit/releases"


def _pip_available() -> bool:
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def _uv_available() -> bool:
    return which("uv") is not None


def _installed_via_uv_tool() -> bool:
    """Best-effort heuristic: is the installed dist located under a uv tools dir?"""
    try:
        dist = distribution("comfygit")
    except PackageNotFoundError:
        return False
    try:
        base = Path(str(dist.locate_file(""))).as_posix().lower()
    except Exception:
        return False
    return "/uv/tools/" in base


def _run(cmd: list[str]) -> int:
    try:
        res = subprocess.run(cmd, check=False)
        return int(res.returncode)
    except FileNotFoundError:
        return 127
    except Exception:
        return 1


class UpdateCommands:
    def update(self, args: argparse.Namespace) -> None:
        """Update the installed `comfygit` CLI package, or check for updates."""
        if getattr(args, "check", False):
            result = update_checker.check_for_update()
            if result and result.update_available:
                print(update_checker.format_update_notice(result.current_version, result.latest_version))
                update_checker.mark_notified(result.latest_version)
                print(f"Releases: {_RELEASES_URL}")
                return

            current = update_checker.get_current_version()
            if not current:
                print("Cannot determine installed version (running from source or package not installed).")
                sys.exit(1)
            print(f"No update available. Current: {current}.")
            return

        current = update_checker.get_current_version()
        if not current:
            print("Cannot determine installed version (running from source or package not installed).")
            print(f"See releases: {_RELEASES_URL}")
            sys.exit(1)

        cmd: list[str] | None = None
        if _uv_available() and _installed_via_uv_tool():
            cmd = ["uv", "tool", "upgrade", "comfygit"]
        elif _pip_available():
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "comfygit"]

        if not cmd:
            print("No supported upgrade method found.")
            print("Try one of:")
            print("  uv tool upgrade comfygit")
            print("  pip install --upgrade comfygit")
            sys.exit(1)

        rc = _run(cmd)
        if rc != 0:
            print(f"Upgrade command failed (exit {rc}): {' '.join(cmd)}")
            sys.exit(rc)

        # Keep MVP scope: no release note parsing, just a link.
        print(f"Updated. Releases: {_RELEASES_URL}")
