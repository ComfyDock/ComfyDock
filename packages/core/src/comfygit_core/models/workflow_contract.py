"""Workflow execution contract models.

These models represent the durable contract shape stored in an environment
manifest. They intentionally model the portable pyproject payload, not manager
editor state, runtime projection rows, or generated ComfyUI API prompts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

WorkflowContractType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "enum",
    "image",
    "video",
    "audio",
    "file",
]

CONTRACT_INPUT_TYPES: set[str] = {
    "string",
    "integer",
    "number",
    "boolean",
    "enum",
    "image",
    "video",
    "audio",
    "file",
}

CONTRACT_OUTPUT_TYPES: set[str] = {
    "image",
    "video",
    "audio",
    "file",
}

ContractValue = str | int | float | bool | list[Any] | dict[str, Any] | None
ContractNodeId = str | int
ContractNumericBound = int | float

TOML_INT_MIN = -(2**63)
TOML_INT_MAX = 2**63 - 1


def _omit_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_number(value: Any) -> ContractNumericBound | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    try:
        if value is None or value == "":
            return None
        text = str(value).strip()
        if text == "":
            return None
        if "." not in text and "e" not in text.lower():
            return int(text)
        parsed = float(text)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _normalize_contract_default(value: Any, input_type: str) -> ContractValue:
    if input_type == "integer":
        parsed = _as_int(value)
        return parsed if parsed is not None else value
    if input_type == "number":
        parsed = _as_number(value)
        return parsed if parsed is not None else value
    if input_type == "boolean":
        if value is None:
            return None
        return _as_bool(value, default=False)
    return value


def _toml_safe_int(value: int) -> int | str:
    if TOML_INT_MIN <= value <= TOML_INT_MAX:
        return value
    return str(value)


def _toml_safe_value(value: Any) -> Any:
    """Return a TOML-compatible value without losing large integer precision.

    TOML integers are signed 64-bit. ComfyUI widgets can expose unsigned 64-bit
    seed bounds, so values outside TOML's integer range are serialized as
    strings and converted back when contract models are loaded.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _toml_safe_int(value)
    if isinstance(value, list):
        return [_toml_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _toml_safe_value(item) for key, item in value.items()}
    return value


def toml_safe_contract_value(value: Any) -> Any:
    """Return a contract value that can be written into `pyproject.toml`."""
    return _toml_safe_value(value)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized else None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


@dataclass
class WorkflowContractInput:
    """A named external input bound to a workflow node/widget field."""

    name: str
    type: str
    node_id: ContractNodeId
    required: bool
    display_name: str | None = None
    widget_idx: int | None = None
    field_key: str | None = None
    default: ContractValue = None
    min: ContractNumericBound | None = None
    max: ContractNumericBound | None = None
    enum_values: list[str] = field(default_factory=list)
    description: str | None = None

    @property
    def widget_index(self) -> int | None:
        """Projection compatibility alias for the durable `widget_idx` field."""
        return self.widget_idx

    @property
    def is_widget_backed(self) -> bool:
        return self.widget_idx is not None

    @property
    def is_numeric(self) -> bool:
        return self.type in {"integer", "number"}

    @property
    def is_enum(self) -> bool:
        return self.type == "enum"

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to the pyproject `execution_contract` shape."""
        payload = {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
            "required": self.required,
            "display_name": self.display_name,
            "widget_idx": self.widget_idx,
            "field_key": self.field_key,
            "default": _toml_safe_value(self.default),
            "min": _toml_safe_value(self.min),
            "max": _toml_safe_value(self.max),
            "enum_values": self.enum_values if self.enum_values else None,
            "description": self.description,
        }
        return _omit_none(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
            "required": self.required,
            "display_name": self.display_name,
            "widget_idx": self.widget_idx,
            "field_key": self.field_key,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "enum_values": self.enum_values if self.enum_values else None,
            "description": self.description,
        }
        return _omit_none(payload)

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "WorkflowContractInput":
        """Deserialize from pyproject data.

        The durable field is `widget_idx`; `widget_index` is accepted as an
        import/projection alias because earlier runtime mapping code used that
        name.
        """
        widget_idx = data.get("widget_idx", data.get("widget_index"))
        return cls(
            name=str(data["name"]),
            type=str(data["type"]),
            node_id=data["node_id"],
            required=_as_bool(data.get("required"), default=True),
            display_name=_as_str(data.get("display_name")),
            widget_idx=_as_int(widget_idx),
            field_key=_as_str(data.get("field_key")),
            default=_normalize_contract_default(data.get("default"), str(data["type"])),
            min=_as_number(data.get("min")),
            max=_as_number(data.get("max")),
            enum_values=_as_str_list(data.get("enum_values")),
            description=_as_str(data.get("description")),
        )


@dataclass
class WorkflowContractOutput:
    """A named external output bound to workflow execution history."""

    name: str
    type: str
    node_id: ContractNodeId
    display_name: str | None = None
    selector: str | None = None
    description: str | None = None

    @property
    def selector_slot(self) -> int | None:
        """Return the numeric slot for selectors shaped as `slot:N`."""
        if not self.selector or not self.selector.startswith("slot:"):
            return None
        return _as_int(self.selector.removeprefix("slot:"))

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to the pyproject `execution_contract` shape."""
        payload = {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
            "display_name": self.display_name,
            "selector": self.selector,
            "description": self.description,
        }
        return _omit_none(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
            "display_name": self.display_name,
            "selector": self.selector,
            "description": self.description,
        }
        return _omit_none(payload)

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "WorkflowContractOutput":
        return cls(
            name=str(data["name"]),
            type=str(data["type"]),
            node_id=data["node_id"],
            display_name=_as_str(data.get("display_name")),
            selector=_as_str(data.get("selector")),
            description=_as_str(data.get("description")),
        )


@dataclass
class NamedWorkflowContract:
    """A named contract variant for one workflow."""

    inputs: list[WorkflowContractInput] = field(default_factory=list)
    outputs: list[WorkflowContractOutput] = field(default_factory=list)
    display_name: str | None = None
    description: str | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.inputs and self.outputs)

    def to_toml_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "inputs": [item.to_toml_dict() for item in self.inputs],
            "outputs": [item.to_toml_dict() for item in self.outputs],
            "display_name": self.display_name,
            "description": self.description,
        }
        return _omit_none(payload)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "display_name": self.display_name,
            "description": self.description,
        }
        return _omit_none(payload)

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "NamedWorkflowContract":
        return cls(
            inputs=[
                WorkflowContractInput.from_toml_dict(item)
                for item in data.get("inputs", [])
                if isinstance(item, dict)
            ],
            outputs=[
                WorkflowContractOutput.from_toml_dict(item)
                for item in data.get("outputs", [])
                if isinstance(item, dict)
            ],
            display_name=_as_str(data.get("display_name")),
            description=_as_str(data.get("description")),
        )


@dataclass
class WorkflowExecutionContract:
    """Top-level execution contract stored under a workflow manifest entry."""

    version: int = 1
    default_contract: str = "default"
    contracts: dict[str, NamedWorkflowContract] = field(default_factory=dict)
    api_prompt_file: str | None = None
    api_prompt_source: str | None = None
    api_prompt_generated_by: str | None = None
    api_prompt_generated_at: str | None = None
    comfyui_version: str | None = None
    manager_version: str | None = None

    @property
    def active_contract(self) -> NamedWorkflowContract | None:
        return self.contracts.get(self.default_contract)

    @property
    def has_contract(self) -> bool:
        return self.active_contract is not None

    def to_toml_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "default_contract": self.default_contract,
            "api_prompt_file": self.api_prompt_file,
            "api_prompt_source": self.api_prompt_source,
            "api_prompt_generated_by": self.api_prompt_generated_by,
            "api_prompt_generated_at": self.api_prompt_generated_at,
            "comfyui_version": self.comfyui_version,
            "manager_version": self.manager_version,
            "contracts": {
                name: contract.to_toml_dict()
                for name, contract in self.contracts.items()
            },
        }
        return _omit_none(payload)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "default_contract": self.default_contract,
            "api_prompt_file": self.api_prompt_file,
            "api_prompt_source": self.api_prompt_source,
            "api_prompt_generated_by": self.api_prompt_generated_by,
            "api_prompt_generated_at": self.api_prompt_generated_at,
            "comfyui_version": self.comfyui_version,
            "manager_version": self.manager_version,
            "contracts": {
                name: contract.to_dict()
                for name, contract in self.contracts.items()
            },
        }
        return _omit_none(payload)

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "WorkflowExecutionContract":
        raw_contracts = data.get("contracts", {})
        contracts: dict[str, NamedWorkflowContract] = {}
        if isinstance(raw_contracts, dict):
            contracts = {
                str(name): NamedWorkflowContract.from_toml_dict(contract_data)
                for name, contract_data in raw_contracts.items()
                if isinstance(contract_data, dict)
            }
        return cls(
            version=_as_int(data.get("version")) or 1,
            default_contract=_as_str(data.get("default_contract")) or "default",
            contracts=contracts,
            api_prompt_file=_as_str(data.get("api_prompt_file")),
            api_prompt_source=_as_str(data.get("api_prompt_source")),
            api_prompt_generated_by=_as_str(data.get("api_prompt_generated_by")),
            api_prompt_generated_at=_as_str(data.get("api_prompt_generated_at")),
            comfyui_version=_as_str(data.get("comfyui_version")),
            manager_version=_as_str(data.get("manager_version")),
        )

    def to_public_schema(self) -> dict[str, Any]:
        """Return the public contract summary used by serve/runtime callers."""
        active = self.active_contract
        if active is None:
            return {"inputs": [], "outputs": []}
        return {
            "inputs": [input_item.to_dict() for input_item in active.inputs],
            "outputs": [output_item.to_dict() for output_item in active.outputs],
        }

    def to_full_dict(self) -> dict[str, Any]:
        """Return all dataclass fields, including empty optional collections."""
        return asdict(self)
