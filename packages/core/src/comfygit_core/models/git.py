"""Typed Git result models exposed through the public core API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GitRemoteBranch:
    """One branch advertised by a remote repository."""

    name: str
    commit: str
    is_default: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitRemoteBranch:
        return cls(
            name=str(data["name"]),
            commit=str(data["commit"]),
            is_default=bool(data.get("is_default", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitRemoteTag:
    """One tag advertised by a remote repository."""

    name: str
    commit: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitRemoteTag:
        return cls(
            name=str(data["name"]),
            commit=str(data["commit"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitRemoteRefs:
    """Importable refs advertised by a remote repository."""

    default_branch: str | None = None
    head_commit: str | None = None
    branches: tuple[GitRemoteBranch, ...] = ()
    tags: tuple[GitRemoteTag, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitRemoteRefs:
        default_branch = data.get("default_branch")
        head_commit = data.get("head_commit")
        return cls(
            default_branch=str(default_branch) if default_branch is not None else None,
            head_commit=str(head_commit) if head_commit is not None else None,
            branches=tuple(
                GitRemoteBranch.from_dict(branch)
                for branch in data.get("branches", [])
                if isinstance(branch, dict)
            ),
            tags=tuple(
                GitRemoteTag.from_dict(tag)
                for tag in data.get("tags", [])
                if isinstance(tag, dict)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_branch": self.default_branch,
            "head_commit": self.head_commit,
            "branches": [branch.to_dict() for branch in self.branches],
            "tags": [tag.to_dict() for tag in self.tags],
        }
