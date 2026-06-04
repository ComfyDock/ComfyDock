"""CLI update checker with caching.

This module intentionally lives in the CLI package (not core) because it uses
user-home config storage (currently `~/.config/comfygit`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

import requests
from packaging.version import InvalidVersion, Version

_PYPY_PROJECT = "comfygit"
_PYPI_URL = f"https://pypi.org/pypi/{_PYPY_PROJECT}/json"
_DEFAULT_TIMEOUT_S = 2.0
_RECHECK_WINDOW = timedelta(hours=24)
UTC = timezone.utc


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_update_check_disabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return _is_truthy_env(env.get("COMFYGIT_NO_UPDATE_CHECK"))


def get_current_version() -> str | None:
    try:
        v = pkg_version(_PYPY_PROJECT)
    except PackageNotFoundError:
        return None
    if not v or v == "unknown":
        return None
    return v


def get_config_dir(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    config_dir = base / ".config" / "comfygit"
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fail silently by design (no permissions, readonly home, etc).
        pass
    return config_dir


def get_cache_path(config_dir: Path | None = None) -> Path:
    cfg = config_dir if config_dir is not None else get_config_dir()
    return cfg / "update_state.json"


@dataclass(frozen=True)
class UpdateState:
    last_checked_at: datetime | None = None
    latest_version: str | None = None
    last_notified_latest_version: str | None = None


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    should_notify: bool


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def load_state(cache_path: Path) -> UpdateState:
    try:
        if not cache_path.exists():
            return UpdateState()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return UpdateState()
        return UpdateState(
            last_checked_at=_parse_dt(data.get("last_checked_at")),
            latest_version=data.get("latest_version") if isinstance(data.get("latest_version"), str) else None,
            last_notified_latest_version=(
                data.get("last_notified_latest_version")
                if isinstance(data.get("last_notified_latest_version"), str)
                else None
            ),
        )
    except Exception:
        return UpdateState()


def save_state(cache_path: Path, state: UpdateState) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_checked_at": state.last_checked_at.astimezone(UTC).isoformat() if state.last_checked_at else None,
            "latest_version": state.latest_version,
            "last_notified_latest_version": state.last_notified_latest_version,
        }
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        # Fail silently by design.
        return


def _should_recheck(state: UpdateState, now: datetime) -> bool:
    if state.last_checked_at is None:
        return True
    age = now - state.last_checked_at
    return age >= _RECHECK_WINDOW


def fetch_latest_version(timeout_s: float = _DEFAULT_TIMEOUT_S) -> str | None:
    try:
        resp = requests.get(_PYPI_URL, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
        info = data.get("info", {})
        if not isinstance(info, dict):
            return None
        v = info.get("version")
        if not isinstance(v, str) or not v.strip():
            return None
        return v.strip()
    except Exception:
        return None


def _safe_version(value: str) -> Version | None:
    try:
        return Version(value)
    except InvalidVersion:
        return None


def format_update_notice(current: str, latest: str) -> str:
    return f"Update available: {current} -> {latest}. Run cg update to upgrade."


def check_for_update(
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    now: datetime | None = None,
    config_dir: Path | None = None,
    environ: dict[str, str] | None = None,
) -> UpdateCheckResult | None:
    """Check PyPI for a newer version with a 24h cached window.

    Returns None when checks are disabled, version is unknown, or on any error.
    """
    try:
        if is_update_check_disabled(environ):
            return None

        current = get_current_version()
        if not current:
            return None

        now_dt = now if now is not None else datetime.now(UTC)
        cache_path = get_cache_path(config_dir)

        state = load_state(cache_path)
        latest = state.latest_version

        if latest is None or _should_recheck(state, now_dt):
            fetched = fetch_latest_version(timeout_s=timeout_s)
            if fetched:
                latest = fetched
                state = UpdateState(
                    last_checked_at=now_dt,
                    latest_version=latest,
                    last_notified_latest_version=state.last_notified_latest_version,
                )
                save_state(cache_path, state)
            else:
                # Network failure: keep any cached latest (even if old), otherwise fail silently.
                if latest is None:
                    return None

        cur_v = _safe_version(current)
        lat_v = _safe_version(latest)
        if cur_v is None or lat_v is None:
            return None

        update_available = lat_v > cur_v
        should_notify = bool(update_available and latest != state.last_notified_latest_version)

        return UpdateCheckResult(
            current_version=current,
            latest_version=latest,
            update_available=update_available,
            should_notify=should_notify,
        )
    except Exception:
        return None


def mark_notified(
    latest_version: str,
    *,
    config_dir: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Persist that we've notified the user about a specific latest version."""
    cache_path = get_cache_path(config_dir)
    state = load_state(cache_path)
    now_dt = now if now is not None else datetime.now(UTC)
    new_state = UpdateState(
        last_checked_at=state.last_checked_at or now_dt,
        latest_version=state.latest_version or latest_version,
        last_notified_latest_version=latest_version,
    )
    save_state(cache_path, new_state)
