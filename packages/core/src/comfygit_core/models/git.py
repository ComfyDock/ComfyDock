"""Typed Git result models exposed through the public core API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GitBranch:
    """One local branch in an environment repository."""

    name: str
    is_current: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitCommitSummary:
    """One commit in an environment commit history listing."""

    hash: str
    message: str
    date: str
    date_relative: str
    refs: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitCommitSummary:
        return cls(
            hash=str(data["hash"]),
            refs=str(data.get("refs", "")),
            message=str(data["message"]),
            date=str(data["date"]),
            date_relative=str(data["date_relative"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitRemote:
    """One configured remote with consolidated fetch and push URLs."""

    name: str
    fetch_url: str
    push_url: str
    is_default: bool = False

    @classmethod
    def from_remote_entries(
        cls,
        entries: list[tuple[str, str, str]],
        *,
        default_remote: str | None = None,
    ) -> tuple[GitRemote, ...]:
        remotes: dict[str, dict[str, str]] = {}
        for name, url, remote_type in entries:
            remote = remotes.setdefault(name, {"fetch_url": "", "push_url": ""})
            if remote_type == "fetch":
                remote["fetch_url"] = url
            elif remote_type == "push":
                remote["push_url"] = url

        return tuple(
            cls(
                name=name,
                fetch_url=urls["fetch_url"],
                push_url=urls["push_url"] or urls["fetch_url"],
                is_default=name == default_remote,
            )
            for name, urls in remotes.items()
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitSyncStatus:
    """Ahead/behind status between local HEAD and a remote branch."""

    ahead: int = 0
    behind: int = 0
    remote_branch_exists: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitSyncStatus:
        return cls(
            ahead=int(data.get("ahead", 0)),
            behind=int(data.get("behind", 0)),
            remote_branch_exists=bool(data.get("remote_branch_exists", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
