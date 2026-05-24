"""Sync option manifest helpers."""
from __future__ import annotations

from typing import Any, cast

from .base import BaseHandler


class SyncConfigHandler(BaseHandler):
    """Handles manifest-backed default sync options."""

    @staticmethod
    def normalize_extra(extra: str) -> str:
        """Normalize optional extras for comparison."""
        return extra.strip().lower().replace("_", "-")

    def dedupe_extras(self, extras: list[str]) -> list[str]:
        """Normalize and deduplicate extras, preserving first-seen order."""
        seen = set()
        result = []
        for extra in extras:
            normalized = self.normalize_extra(extra)
            if not normalized or normalized in seen:
                continue
            result.append(normalized)
            seen.add(normalized)
        return result

    def get_extras(self) -> list[str]:
        """Get default optional extras to install during sync."""
        config = self.load()
        return list(
            config.get("tool", {})
            .get("comfygit", {})
            .get("sync", {})
            .get("extras", [])
        )

    def set_extras(self, extras: list[str]) -> None:
        """Set default optional extras to install during sync."""
        normalized = self.dedupe_extras(extras)
        with self.manager.edit() as raw_config:
            config = cast(dict[str, Any], raw_config)
            comfygit = self.ensure_section(config, "tool", "comfygit")

            sync_config = comfygit.get("sync", {})
            if not isinstance(sync_config, dict):
                sync_config = {}
            if normalized:
                sync_config["extras"] = normalized
                comfygit["sync"] = sync_config
            else:
                sync_config.pop("extras", None)
                if not sync_config:
                    comfygit.pop("sync", None)

    def add_extra(self, extra: str) -> bool:
        """Add a default sync extra. Returns True if added."""
        current = self.get_extras()
        updated = self.dedupe_extras(current + [extra])
        if updated == self.dedupe_extras(current):
            return False
        self.set_extras(updated)
        return True

    def remove_extra(self, extra: str) -> bool:
        """Remove a default sync extra. Returns True if removed."""
        target = self.normalize_extra(extra)
        if not target:
            return False
        current = self.get_extras()
        updated = [item for item in current if self.normalize_extra(item) != target]
        if updated == current:
            return False
        self.set_extras(updated)
        return True

    def resolve_extras(
        self,
        extras: list[str] | None,
        all_extras: bool,
    ) -> tuple[list[str] | None, bool]:
        """Merge default sync extras with explicit extras."""
        if all_extras:
            return None, True
        merged = self.dedupe_extras(self.get_extras() + (extras or []))
        return (merged or None), False
