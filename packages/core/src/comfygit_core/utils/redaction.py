"""Helpers for redacting sensitive values before logging."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "client_secret",
    "key",
    "secret",
    "signature",
    "sig",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
}

_INLINE_TOKEN_PATTERN = re.compile(
    r"(?i)\b([a-z0-9]*(?:[_-][a-z0-9]+)*[_-]?"
    r"(?:authorization|bearer|token|api[_-]?key|client[_-]?secret|password|credential|key)"
    r"(?:[_-][a-z0-9]+)*)"
    r"(\s*[:=]\s*|\s+)[^\s,'\")]+"
)
_SENSITIVE_FIELD_SEGMENTS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "credentials",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}
_SENSITIVE_FLAG_NAMES = {
    "--access-token",
    "--api-key",
    "--apikey",
    "--auth",
    "--authorization",
    "--client-secret",
    "--civitai-key",
    "--github-token",
    "--hf-token",
    "--huggingface-token",
    "--password",
    "--secret",
    "--token",
}


def redact_url(url: str) -> str:
    """Redact sensitive URL credentials and query parameters."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact_sensitive_text(url)

    netloc = parts.netloc
    if "@" in netloc:
        _, host = netloc.rsplit("@", 1)
        netloc = f"<redacted>@{host}"

    query = parse_qsl(parts.query, keep_blank_values=True)
    if query:
        query = [
            (key, "<redacted>" if key.lower() in SENSITIVE_QUERY_KEYS else value)
            for key, value in query
        ]
    return urlunsplit(
        (parts.scheme, netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
    )


def redact_sensitive_text(value: object) -> str:
    """Redact token-like values in arbitrary log text."""
    text = str(value)

    def _replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}<redacted>"

    return _INLINE_TOKEN_PATTERN.sub(_replace, text)


def is_sensitive_field_name(name: object) -> bool:
    """Return whether a structured field name denotes secret-bearing data."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    if normalized in _SENSITIVE_FIELD_SEGMENTS:
        return True
    parts = set(normalized.split("_"))
    return bool(parts & {"auth", "authorization", "credential", "credentials", "key", "password", "secret", "token"})


def redact_sensitive_value(value: Any) -> Any:
    """Recursively redact secret-bearing values while preserving safe structure."""
    if isinstance(value, Mapping):
        return redact_sensitive_mapping({str(key): item for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(redact_sensitive_value(item) for item in value)
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, set):
        return {redact_sensitive_value(item) for item in value}
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_sensitive_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of a mapping with sensitive fields fully removed."""
    return {
        key: "<redacted>" if is_sensitive_field_name(key) else redact_sensitive_value(value)
        for key, value in values.items()
    }


def redact_command(cmd: Iterable[object]) -> str:
    """Return a shell-ish command string safe for debug logs."""
    redacted: list[str] = []
    redact_next = False
    for raw_part in cmd:
        part = str(raw_part)
        flag = part.split("=", 1)[0].lower()
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if flag in _SENSITIVE_FLAG_NAMES:
            if "=" in part:
                redacted.append(f"{part.split('=', 1)[0]}=<redacted>")
            else:
                redacted.append(part)
                redact_next = True
            continue
        redacted.append(redact_sensitive_text(part))
    return " ".join(redacted)
