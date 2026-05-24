"""Document storage for pyproject-backed ComfyGit manifests."""
from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError

from ..logging.logging_config import get_logger
from ..models.exceptions import CDPyprojectError, CDPyprojectInvalidError, CDPyprojectNotFoundError
from ..models.workflow_contract import toml_safe_contract_value

logger = get_logger(__name__)


class PyprojectStore:
    """Owns pyproject.toml disk I/O, cache freshness, and TOML formatting."""

    _total_load_calls = 0

    def __init__(self, path: Path):
        self.path = path
        self._instance_load_calls = 0
        self._config_cache: dict | None = None
        self._cache_mtime: float | None = None

    def exists(self) -> bool:
        """Check if the pyproject.toml file exists."""
        return self.path.exists()

    def get_load_stats(self) -> dict:
        """Get statistics about pyproject.toml load operations."""
        return {
            "instance_loads": self._instance_load_calls,
            "total_loads": PyprojectStore._total_load_calls,
        }

    @classmethod
    def reset_load_stats(cls) -> None:
        """Reset class-level load statistics."""
        cls._total_load_calls = 0

    def reset_cache(self) -> None:
        """Invalidate this store's cached TOML document."""
        self._config_cache = None
        self._cache_mtime = None

    def load(self, force_reload: bool = False) -> dict:
        """Load the pyproject.toml file with instance-level caching."""
        if not self.exists():
            raise CDPyprojectNotFoundError(f"pyproject.toml not found at {self.path}")

        current_mtime = self.path.stat().st_mtime

        if (
            not force_reload
            and self._config_cache is not None
            and self._cache_mtime == current_mtime
        ):
            logger.debug("[PYPROJECT CACHE HIT] Using cached config")
            return self._config_cache

        PyprojectStore._total_load_calls += 1
        self._instance_load_calls += 1

        debug_enabled = logger.isEnabledFor(logging.DEBUG)
        start_time = 0.0
        caller_info = "unknown"
        if debug_enabled:
            stack = traceback.extract_stack()
            caller_frame = stack[-2] if len(stack) >= 2 else None
            caller_info = (
                f"{caller_frame.filename}:{caller_frame.lineno} in {caller_frame.name}"
                if caller_frame
                else "unknown"
            )
            start_time = time.perf_counter()

        try:
            with open(self.path, encoding="utf-8") as file:
                config = tomlkit.load(file)
        except (OSError, TOMLKitError) as exc:
            raise CDPyprojectInvalidError(
                f"Failed to parse pyproject.toml at {self.path}: {exc}"
            ) from exc

        if not config:
            raise CDPyprojectInvalidError(f"pyproject.toml is empty at {self.path}")

        self._config_cache = config
        self._cache_mtime = current_mtime

        if debug_enabled:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                f"[PYPROJECT LOAD #{self._instance_load_calls}/{PyprojectStore._total_load_calls}] "
                f"Loaded pyproject.toml in {elapsed_ms:.2f}ms | "
                f"Called from: {caller_info}"
            )

        return config

    def save(self, config: dict | None = None) -> None:
        """Save the configuration to pyproject.toml."""
        if config is None:
            raise CDPyprojectError("No configuration to save")

        self.sanitize_workflow_contracts_for_toml(config)
        self.cleanup_empty_sections(config)
        self.ensure_section_spacing(config)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as file:
                tomlkit.dump(config, file)
        except OSError as exc:
            raise CDPyprojectError(
                f"Failed to write pyproject.toml to {self.path}: {exc}"
            ) from exc

        self.reset_cache()
        logger.debug(f"Saved pyproject.toml to {self.path}")

    def snapshot(self) -> bytes:
        """Capture current pyproject.toml file contents for rollback."""
        return self.path.read_bytes()

    def restore(self, snapshot: bytes) -> None:
        """Restore pyproject.toml from previously captured bytes."""
        self.path.write_bytes(snapshot)
        self.reset_cache()
        logger.debug("Restored pyproject.toml from snapshot")

    def sanitize_workflow_contracts_for_toml(self, config: dict) -> bool:
        """Make workflow contract numeric fields safe for TOML writers."""
        changed = False
        workflows = (
            config.get("tool", {})
            .get("comfygit", {})
            .get("workflows", {})
        )
        if not isinstance(workflows, dict):
            return False

        for workflow_data in workflows.values():
            if not isinstance(workflow_data, dict):
                continue
            execution_contract = workflow_data.get("execution_contract")
            if not isinstance(execution_contract, dict):
                continue
            contracts = execution_contract.get("contracts", {})
            if not isinstance(contracts, dict):
                continue

            for contract_data in contracts.values():
                if not isinstance(contract_data, dict):
                    continue
                inputs = contract_data.get("inputs", [])
                if not isinstance(inputs, list):
                    continue

                for input_data in inputs:
                    if not isinstance(input_data, dict):
                        continue
                    for key in ("default", "min", "max"):
                        if key not in input_data:
                            continue
                        original_value = input_data[key]
                        safe_value = toml_safe_contract_value(original_value)
                        if safe_value != original_value or type(safe_value) is not type(original_value):
                            input_data[key] = safe_value
                            changed = True

        return changed

    def cleanup_empty_sections(self, config: dict) -> None:
        """Recursively remove empty sections from config."""

        def clean_dict(value: dict) -> bool:
            keys_to_remove = []
            for key, child in list(value.items()):
                if isinstance(child, dict) and (clean_dict(child) or not child):
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del value[key]
            return not value

        clean_dict(config)

    def ensure_section_spacing(self, config: dict) -> None:
        """Ensure visual spacing between major ``tool.comfygit`` sections."""
        if "tool" not in config or "comfygit" not in config["tool"]:
            return

        comfygit = config["tool"]["comfygit"]

        has_metadata = any(k in comfygit for k in ["comfyui_version", "python_version", "manifest_state"])
        has_nodes = "nodes" in comfygit
        has_workflows = "workflows" in comfygit
        has_models = "models" in comfygit

        if not (has_workflows or has_models):
            return

        def deep_copy_table(value):
            if isinstance(value, dict):
                is_inline = hasattr(value, "__class__") and "InlineTable" in value.__class__.__name__
                new_dict = tomlkit.inline_table() if is_inline else tomlkit.table()
                for key, child in value.items():
                    if key == "":
                        continue
                    new_dict[key] = deep_copy_table(child)
                return new_dict
            if isinstance(value, list):
                is_tomlkit_array = hasattr(value, "__class__") and "Array" in value.__class__.__name__
                if is_tomlkit_array:
                    new_array = tomlkit.array()
                    for item in value:
                        if hasattr(item, "__class__") and "InlineTable" in item.__class__.__name__:
                            new_inline = tomlkit.inline_table()
                            for key, child in item.items():
                                new_inline[key] = deep_copy_table(child)
                            new_array.append(new_inline)
                        else:
                            new_array.append(deep_copy_table(item))
                    return new_array
                return [deep_copy_table(item) for item in value]
            return value

        new_table = tomlkit.table()

        for key, value in comfygit.items():
            if key in {"nodes", "workflows", "models"}:
                continue
            if key == "":
                continue
            new_table[key] = deep_copy_table(value)

        if has_nodes:
            new_table["nodes"] = deep_copy_table(comfygit["nodes"])

        if has_workflows:
            if has_metadata or has_nodes:
                new_table.add(tomlkit.nl())
            new_table["workflows"] = deep_copy_table(comfygit["workflows"])

        if has_models:
            if has_metadata or has_nodes or has_workflows:
                new_table.add(tomlkit.nl())
            new_table["models"] = deep_copy_table(comfygit["models"])

        config["tool"]["comfygit"] = new_table
