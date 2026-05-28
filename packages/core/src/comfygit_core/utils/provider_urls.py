"""Provider URL classification helpers."""

from __future__ import annotations

from urllib.parse import urlparse


def _hostname(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().rstrip(".")


def host_matches(url: str, allowed_hosts: set[str]) -> bool:
    """Return true when a URL host is exactly an allowed host or subdomain."""
    host = _hostname(url)
    if not host:
        return False
    for allowed in allowed_hosts:
        allowed = allowed.lower().rstrip(".")
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


def is_civitai_url(url: str) -> bool:
    """Return true when a URL is hosted by CivitAI."""
    return host_matches(url, {"civitai.com"})


def is_huggingface_url(url: str) -> bool:
    """Return true when a URL is hosted by Hugging Face."""
    return host_matches(url, {"huggingface.co", "hf.co"})
