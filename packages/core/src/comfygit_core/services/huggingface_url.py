"""HuggingFace URL parsing utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

Kind = Literal["repo", "file", "unknown"]


@dataclass(frozen=True)
class ParsedHuggingFaceUrl:
    """Parsed HuggingFace URL with extracted components."""

    kind: Kind
    repo_id: str | None = None
    revision: str | None = None
    path_in_repo: str | None = None


def parse_huggingface_url(url: str) -> ParsedHuggingFaceUrl:
    """Parse a HuggingFace URL into its components.

    Handles these URL patterns:
    - https://huggingface.co/owner/repo -> kind="repo"
    - https://huggingface.co/owner/repo/tree/main -> kind="repo"
    - https://huggingface.co/owner/repo/resolve/main/file.safetensors -> kind="file"
    - https://huggingface.co/owner/repo/blob/main/file.safetensors -> kind="file"
    - https://civitai.com/... -> kind="unknown"

    Args:
        url: URL to parse

    Returns:
        ParsedHuggingFaceUrl with kind, repo_id, revision, and path_in_repo
    """
    u = url.strip()
    if not u:
        return ParsedHuggingFaceUrl(kind="unknown")

    try:
        p = urlparse(u)
    except Exception:
        return ParsedHuggingFaceUrl(kind="unknown")

    host = (p.hostname or "").lower()
    if host not in ("huggingface.co", "hf.co") and not host.endswith(".huggingface.co"):
        return ParsedHuggingFaceUrl(kind="unknown")

    parts = [s for s in p.path.split("/") if s]

    # Ignore datasets/spaces in MVP
    if not parts or parts[0] in ("datasets", "spaces"):
        return ParsedHuggingFaceUrl(kind="unknown")

    if len(parts) < 2:
        return ParsedHuggingFaceUrl(kind="unknown")

    repo_id = f"{parts[0]}/{parts[1]}"
    revision = "main"

    # Just owner/repo -> repo page
    if len(parts) == 2:
        return ParsedHuggingFaceUrl(kind="repo", repo_id=repo_id, revision=revision)

    marker = parts[2]

    # /tree/<revision> -> repo browser
    if marker == "tree":
        revision = parts[3] if len(parts) >= 4 else "main"
        return ParsedHuggingFaceUrl(kind="repo", repo_id=repo_id, revision=revision)

    # /resolve/<revision>/<path> or /blob/<revision>/<path> -> file
    if marker in ("resolve", "blob"):
        revision = parts[3] if len(parts) >= 4 else "main"
        path_in_repo = "/".join(parts[4:]) if len(parts) >= 5 else ""
        if not path_in_repo:
            return ParsedHuggingFaceUrl(kind="repo", repo_id=repo_id, revision=revision)
        return ParsedHuggingFaceUrl(
            kind="file",
            repo_id=repo_id,
            revision=revision,
            path_in_repo=path_in_repo,
        )

    # Unknown marker, treat as repo
    return ParsedHuggingFaceUrl(kind="repo", repo_id=repo_id, revision="main")
