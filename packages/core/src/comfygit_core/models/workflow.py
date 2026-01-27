from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models.node_mapping import (
    GlobalNodePackage,
)
from ..services.model_downloader import ModelDownloader
from ..utils.uuid import is_uuid

if TYPE_CHECKING:
    from .shared import ModelWithLocation, NodeInfo


@dataclass
class ScoredMatch:
    """Model match with similarity score."""
    model: ModelWithLocation
    score: float
    confidence: str  # "high", "good", "possible"


@dataclass
class ScoredPackageMatch:
    """Node package match with similarity score for fuzzy search."""
    package_id: str
    package_data: GlobalNodePackage
    score: float
    confidence: str  # "high", "medium", "low"


@dataclass
class NodeResolutionContext:
    """Context for enhanced node resolution with state tracking."""

    # Existing packages in environment
    installed_packages: dict[str, NodeInfo] = field(default_factory=dict)

    # User-defined mappings (persisted in pyproject.toml)
    custom_mappings: dict[str, str | bool] = field(default_factory=dict)  # node_type -> package_id or false (for optional node)

    # Current workflow context
    workflow_name: str = ""

    # Search function for fuzzy package matching (injected by workflow_manager)
    # Signature: (node_type: str, installed_packages: dict, include_registry: bool, limit: int) -> list[ResolvedNodePackage]
    search_fn: Callable | None = None

    # Auto-selection configuration (post-MVP: make this configurable via config file)
    auto_select_ambiguous: bool = True  # Auto-select best package from registry mappings

@dataclass
class WorkflowModelNodeMapping:
    nodes: list[WorkflowNodeWidgetRef]

@dataclass
class BatchDownloadCallbacks:
    """Callbacks for batch download coordination in core library.

    All callbacks are optional - if None, core library performs operation silently.
    CLI package provides implementations that render to terminal.
    """

    # Called once at start with total number of files
    on_batch_start: Callable[[int], None] | None = None

    # Called before each file download (filename, current_index, total_count)
    on_file_start: Callable[[str, int, int], None] | None = None

    # Called during download for progress updates (bytes_downloaded, total_bytes)
    on_file_progress: Callable[[int, int | None], None] | None = None

    # Called after each file completes (filename, success, error_message)
    on_file_complete: Callable[[str, bool, str | None], None] | None = None

    # Called once at end (success_count, total_count)
    on_batch_complete: Callable[[int, int], None] | None = None


@dataclass
class NodeInstallCallbacks:
    """Callbacks for node installation progress in core library.

    All callbacks are optional - if None, core library performs operation silently.
    CLI package provides implementations that render to terminal.
    """

    # Called once at start with total number of nodes
    on_batch_start: Callable[[int], None] | None = None

    # Called before each node installation (node_id, current_index, total_count)
    on_node_start: Callable[[str, int, int], None] | None = None

    # Called after each node completes (node_id, success, error_message)
    on_node_complete: Callable[[str, bool, str | None], None] | None = None

    # Called once at end (success_count, total_count)
    on_batch_complete: Callable[[int, int], None] | None = None


@dataclass
class ModelResolutionContext:
    """Context for model resolution with search function and workflow info."""
    workflow_name: str

    # Lookup: ref → ManifestWorkflowModel (full model object with hash, sources, status, etc.)
    # Changed from dict[WorkflowNodeWidgetRef, str] to support download intent detection
    previous_resolutions: dict[WorkflowNodeWidgetRef, Any] = field(default_factory=dict)  # TYPE_CHECKING: ManifestWorkflowModel

    # Global models table: hash → ManifestGlobalModel (for download intent creation)
    global_models: dict[str, Any] = field(default_factory=dict)  # TYPE_CHECKING: ManifestGlobalModel

    # Search function for fuzzy matching (injected by workflow_manager)
    # Signature: (search_term: str, node_type: str | None, limit: int) -> list[ScoredMatch]
    search_fn: Callable | None = None

    # Model downloader for URL-based downloads (injected by workflow_manager)
    downloader: ModelDownloader | None = None

    # Auto-selection configuration (for automated strategies)
    auto_select_ambiguous: bool = True


@dataclass
class Link:
    """Represents a connection between nodes."""
    id: int
    source_node_id: int
    source_slot: int
    target_node_id: int
    target_slot: int
    type: str

    def to_array(self) -> list:
        """Convert to ComfyUI's [id, source_node, source_slot, target_node,
        target_slot, type] format."""
        return [self.id, self.source_node_id, self.source_slot, self.target_node_id, self.target_slot, self.type]

    @classmethod
    def from_array(cls, arr: list) -> Link:
        """Parse from ComfyUI's array format."""
        return cls(arr[0], arr[1], arr[2], arr[3], arr[4], arr[5])

@dataclass
class Group:
    """Represents a visual grouping of nodes."""
    id: int
    title: str
    bounding: tuple[float, float, float, float]  # [x, y, width, height]
    color: str
    font_size: int = 24
    flags: dict[str, Any] = field(default_factory=dict)

@dataclass
class Workflow:
    """Complete parsed workflow representation."""

    # Core data
    nodes: dict[str, WorkflowNode]  # Keep as dict for easier access

    # Graph structure
    links: list[Link] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)

    # Metadata (exactly as in your examples)
    id: str | None = None
    revision: int = 0
    last_node_id: int | None = None
    last_link_id: int | None = None
    version: float | None = None

    # Flexible containers (don't break these out into separate fields!)
    config: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    # Subgraph reconstruction metadata (private)
    _subgraph_metadata: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        """Concise representation showing node count and types."""
        node_count = len(self.nodes)
        type_summary = ", ".join(sorted(set(n.type for n in self.nodes.values()))[:5])
        if len(self.node_types) > 5:
            type_summary += f", ... ({len(self.node_types) - 5} more types)"
        return f"Workflow(nodes={node_count}, types=[{type_summary}])"

    @cached_property
    def node_types(self) -> set[str]:
        return {node.type for node in self.nodes.values()}

    @classmethod
    def from_json(cls, data: dict) -> Workflow:
        """Parse from ComfyUI workflow JSON.

        Supports subgraphs (ComfyUI v1.24.3+): nodes inside subgraphs are extracted
        and flattened, while UUID-based subgraph references are filtered out.

        Stores metadata needed to reconstruct original structure in to_json().
        """
        # Build set of subgraph IDs for filtering UUID references
        subgraph_ids = set()
        if 'definitions' in data and 'subgraphs' in data['definitions']:
            subgraph_ids = {sg['id'] for sg in data['definitions']['subgraphs']}

        nodes = {}
        subgraph_metadata = {}

        # Parse top-level nodes (skip subgraph references but remember them)
        top_level_uuid_refs = []
        if isinstance(data.get('nodes'), list):
            for node in data['nodes']:
                node_type = node.get('type') or node.get('class_type') or ''
                if node_type in subgraph_ids or is_uuid(node_type):
                    # Store UUID reference node for reconstruction
                    top_level_uuid_refs.append(node)
                else:
                    nodes[str(node['id'])] = WorkflowNode.from_dict(node)
        else:
            for k, v in data.get('nodes', {}).items():
                node_type = v.get('type') or v.get('class_type') or ''
                if node_type in subgraph_ids or is_uuid(node_type):
                    top_level_uuid_refs.append(v)
                else:
                    nodes[k] = WorkflowNode.from_dict(v)

        # Parse subgraph nodes (flatten all subgraphs) + capture ALL metadata for lossless round-trip
        if 'definitions' in data and 'subgraphs' in data['definitions']:
            for subgraph in data['definitions']['subgraphs']:
                subgraph_id = subgraph['id']

                # Capture complete subgraph structure for round-trip preservation
                # Required for ComfyUI Zod schema compliance
                subgraph_metadata[subgraph_id] = {
                    # Core identity
                    'name': subgraph.get('name', ''),

                    # Schema-required fields
                    'version': subgraph.get('version', 1),
                    'revision': subgraph.get('revision', 0),
                    'state': subgraph.get('state', {}),
                    'config': subgraph.get('config', {}),

                    # I/O structure
                    'inputNode': subgraph.get('inputNode'),
                    'outputNode': subgraph.get('outputNode'),
                    'inputs': subgraph.get('inputs', []),
                    'outputs': subgraph.get('outputs', []),
                    'widgets': subgraph.get('widgets', []),

                    # Graph structure (nodes/links handled separately)
                    'links': subgraph.get('links', []),
                    'groups': subgraph.get('groups', []),

                    # Optional metadata
                    'extra': subgraph.get('extra', {}),

                    # Internal tracking (not serialized as-is)
                    'node_ids': [],  # Will be populated below
                    'uuid_refs': []  # Nested subgraph references within this subgraph
                }

                for node in subgraph.get('nodes', []):
                    node_type = node.get('type') or node.get('class_type') or ''
                    node_id = str(node.get('id', 'unknown'))

                    # Check if this is a nested subgraph reference
                    if node_type in subgraph_ids or is_uuid(node_type):
                        # Store nested UUID reference for reconstruction
                        subgraph_metadata[subgraph_id]['uuid_refs'].append(node)
                    else:
                        # Real node - flatten it
                        scoped_id = f"{subgraph_id}:{node_id}"
                        nodes[scoped_id] = WorkflowNode.from_dict(node, subgraph_id=subgraph_id)
                        subgraph_metadata[subgraph_id]['node_ids'].append(scoped_id)

        # Parse links from arrays
        links = [Link.from_array(link) for link in data.get('links', [])]

        # Parse groups (if present)
        groups = [Group(**group) for group in data.get('groups', [])]

        # Store top-level UUID refs in metadata for reconstruction
        if top_level_uuid_refs:
            for ref in top_level_uuid_refs:
                sg_id = ref.get('type')
                if sg_id in subgraph_metadata:
                    subgraph_metadata[sg_id]['top_level_ref'] = ref

        # DO NOT store definitions in extra - we'll reconstruct it in to_json()
        extra = data.get('extra', {}).copy()

        return cls(
            nodes=nodes,
            links=links,
            groups=groups,
            id=data.get('id'),
            revision=data.get('revision', 0),
            last_node_id=data.get('last_node_id'),
            last_link_id=data.get('last_link_id'),
            version=data.get('version'),
            config=data.get('config', {}),
            extra=extra,
            _subgraph_metadata=subgraph_metadata
        )

    def to_json(self) -> dict:
        """Convert back to ComfyUI workflow format.

        Reconstructs original structure with subgraphs if metadata is present.
        """
        # Separate nodes by origin
        top_level_nodes = []
        subgraph_nodes_by_id = {}

        for scoped_id, node in self.nodes.items():
            if node.subgraph_id is None:
                # Top-level node
                top_level_nodes.append(node.to_dict())
            else:
                # Subgraph node - restore original ID
                if node.subgraph_id not in subgraph_nodes_by_id:
                    subgraph_nodes_by_id[node.subgraph_id] = []

                # Extract original node ID from scoped ID (format: "subgraph-uuid:10")
                original_id = scoped_id.split(':', 1)[1] if ':' in scoped_id else scoped_id
                node_dict = node.to_dict()
                node_dict['id'] = int(original_id) if original_id.isdigit() else original_id
                subgraph_nodes_by_id[node.subgraph_id].append(node_dict)

        # Build result
        result = {
            'id': self.id,
            'revision': self.revision,
            'last_node_id': self.last_node_id,
            'last_link_id': self.last_link_id,
            'links': [link.to_array() for link in self.links],
            'groups': [asdict(group) for group in self.groups],
            'config': self.config,
            'version': self.version
        }

        # Reconstruct subgraphs if metadata exists
        if self._subgraph_metadata:
            definitions = {'subgraphs': []}

            for sg_id, metadata in self._subgraph_metadata.items():
                # Get nodes for this subgraph
                sg_nodes = subgraph_nodes_by_id.get(sg_id, [])

                # Add nested UUID references back
                if metadata.get('uuid_refs'):
                    sg_nodes.extend(metadata['uuid_refs'])

                # Reconstruct complete subgraph structure with all fields
                subgraph_dict = {
                    'id': sg_id,
                    'version': metadata.get('version', 1),
                    'state': metadata.get('state', {}),
                    'revision': metadata.get('revision', 0),
                    'config': metadata.get('config', {}),
                    'name': metadata.get('name', ''),
                    'inputNode': metadata.get('inputNode'),
                    'outputNode': metadata.get('outputNode'),
                    'inputs': metadata.get('inputs', []),
                    'outputs': metadata.get('outputs', []),
                    'widgets': metadata.get('widgets', []),
                    'nodes': sg_nodes,
                    'groups': metadata.get('groups', []),
                    'links': metadata.get('links', []),
                    'extra': metadata.get('extra', {})
                }
                definitions['subgraphs'].append(subgraph_dict)

            # Add definitions to top level
            result['definitions'] = definitions

            # Add top-level UUID reference nodes
            for sg_id, metadata in self._subgraph_metadata.items():
                if 'top_level_ref' in metadata:
                    top_level_nodes.append(metadata['top_level_ref'])

        # Add nodes to result
        result['nodes'] = top_level_nodes

        # Add extra (without definitions, since it's at top level now)
        result['extra'] = self.extra

        return result

@dataclass
class NodeInput:
    """Represents a node input definition."""
    name: str
    type: str
    link: int | None = None
    localized_name: str | None = None
    widget: dict[str, Any] | None = None
    shape: int | None = None
    slot_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict format."""
        result: dict = {
            'name': self.name,
            'type': self.type
        }
        if self.link is not None:
            result['link'] = self.link
        if self.localized_name is not None:
            result['localized_name'] = self.localized_name
        if self.widget is not None:
            result['widget'] = self.widget
        if self.shape is not None:
            result['shape'] = self.shape
        if self.slot_index is not None:
            result['slot_index'] = self.slot_index
        return result


@dataclass
class NodeOutput:
    """Represents a node output definition."""
    name: str
    type: str
    links: list[int] | None = None
    localized_name: str | None = None
    slot_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict format."""
        result: dict = {
            'name': self.name,
            'type': self.type
        }
        if self.links is not None:
            result['links'] = self.links
        if self.localized_name is not None:
            result['localized_name'] = self.localized_name
        if self.slot_index is not None:
            result['slot_index'] = self.slot_index
        return result


@dataclass
class WorkflowNode:
    """Complete workflow node with all available data."""
    id: str
    type: str

    # Core data - dual naming for compatibility
    api_widget_values: dict[str, Any] = field(default_factory=dict)  # For convenience/internal use
    widgets_values: list[Any] = field(default_factory=list)  # Frontend format

    # UI positioning
    pos: tuple[float, float] | None = None
    size: tuple[float, float] | None = None

    # UI state
    flags: dict[str, Any] = field(default_factory=dict)
    order: int | None = None
    mode: int | None = None
    title: str | None = None
    color: str | None = None
    bgcolor: str | None = None

    # Connections
    inputs: list[NodeInput] = field(default_factory=list)
    outputs: list[NodeOutput] = field(default_factory=list)

    # Extended properties
    properties: dict[str, Any] = field(default_factory=dict)

    # Subgraph context (for nodes inside subgraphs)
    subgraph_id: str | None = None

    def __repr__(self) -> str:
        """Concise representation showing only id and type."""
        return f"WorkflowNode(id={self.id!r}, type={self.type!r})"

    @property
    def class_type(self) -> str:
        """Alias for API format compatibility."""
        return self.type

    def to_api_format(self) -> dict:
        """Convert to ComfyUI API format."""
        inputs = {}

        # Handle connections and widget values
        widget_idx = 0
        for inp in self.inputs:
            if inp.link is not None:
                # Connected input: [source_node_id, output_slot]
                inputs[inp.name] = [str(inp.link), inp.slot_index or 0]
            elif inp.widget and widget_idx < len(self.widgets_values):
                # Widget input: use value from widgets_values array
                inputs[inp.name] = self.widgets_values[widget_idx]
                widget_idx += 1

        return {
            "class_type": self.type,
            "inputs": inputs
        }

    @classmethod
    def from_dict(cls, data: dict, subgraph_id: str | None = None) -> WorkflowNode:
        """Parse from workflow node dict.

        Args:
            data: Node data dict from workflow JSON
            subgraph_id: Optional subgraph ID if node is inside a subgraph
        """
        # Parse inputs
        inputs = []
        raw_inputs = data.get('inputs', [])
        if isinstance(raw_inputs, list):
            for idx, input_data in enumerate(raw_inputs):
                if isinstance(input_data, dict):
                    inputs.append(NodeInput(
                        name=input_data.get('name', ''),
                        type=input_data.get('type', ''),
                        link=input_data.get('link'),
                        localized_name=input_data.get('localized_name'),
                        widget=input_data.get('widget'),
                        shape=input_data.get('shape'),
                        slot_index=input_data.get('slot_index', idx)
                    ))

        # Parse outputs
        outputs = []
        raw_outputs = data.get('outputs', [])
        if isinstance(raw_outputs, list):
            for idx, output_data in enumerate(raw_outputs):
                if isinstance(output_data, dict):
                    outputs.append(NodeOutput(
                        name=output_data.get('name', ''),
                        type=output_data.get('type', ''),
                        links=output_data.get('links'),
                        localized_name=output_data.get('localized_name'),
                        slot_index=output_data.get('slot_index', idx)
                    ))

        # Parse position and size
        pos = None
        if 'pos' in data and isinstance(data['pos'], list) and len(data['pos']) >= 2:
            pos = (float(data['pos'][0]), float(data['pos'][1]))

        size = None
        if 'size' in data and isinstance(data['size'], list) and len(data['size']) >= 2:
            size = (float(data['size'][0]), float(data['size'][1]))

        # Handle dual naming convention for widget values
        widgets_values = data.get('widgets_values', [])
        widget_values = data.get('widget_values', widgets_values)

        return cls(
            id=str(data.get('id', 'unknown')),
            type=data.get('type') or data.get('class_type') or '',
            api_widget_values=widget_values,
            widgets_values=widgets_values,
            pos=pos,
            size=size,
            flags=data.get('flags', {}),
            order=data.get('order'),
            mode=data.get('mode'),
            title=data.get('title'),
            color=data.get('color'),
            bgcolor=data.get('bgcolor'),
            inputs=inputs,
            outputs=outputs,
            properties=data.get('properties', {}),
            subgraph_id=subgraph_id
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict format."""
        result = {
            'id': int(self.id) if self.id.isdigit() else self.id,
            'type': self.type,
            'widgets_values': self.widgets_values,
            'inputs': [inp.to_dict() for inp in self.inputs],
            'outputs': [out.to_dict() for out in self.outputs],
            'properties': self.properties,
            'flags': self.flags
        }

        # Add optional fields only if they have values
        if self.pos is not None:
            result['pos'] = list(self.pos)
        if self.size is not None:
            result['size'] = list(self.size)
        if self.order is not None:
            result['order'] = self.order
        if self.mode is not None:
            result['mode'] = self.mode
        if self.title is not None:
            result['title'] = self.title
        if self.color is not None:
            result['color'] = self.color
        if self.bgcolor is not None:
            result['bgcolor'] = self.bgcolor

        return result


@dataclass
class InstalledPackageInfo:
    """Information about an already-installed package."""

    package_id: str
    display_name: str | None
    installed_version: str
    suggested_version: str | None = None

    @property
    def version_mismatch(self) -> bool:
        """Check if installed version differs from suggested."""
        return bool(self.suggested_version and
                   self.installed_version != self.suggested_version)

@dataclass
class WorkflowNodeWidgetRef:
    """Reference to a widget value in a workflow node.

    Core identity fields: node_id, node_type, widget_index, widget_value
    Optional metadata fields: property_url, property_directory (from properties.models)

    Hash/eq are based only on core identity fields for deduplication.
    """
    node_id: str
    node_type: str
    widget_index: int
    widget_value: str  # Original value from workflow

    # Optional metadata from properties.models (for download intent creation)
    property_url: str | None = None
    property_directory: str | None = None

    def __eq__(self, value: object) -> bool:
        """Compare based on core identity fields only (excludes property metadata)."""
        if isinstance(value, WorkflowNodeWidgetRef):
            return (self.node_id == value.node_id and
                    self.node_type == value.node_type and
                    self.widget_index == value.widget_index and
                    self.widget_value == value.widget_value)
        return False

    def __hash__(self) -> int:
        """Hash based on core identity fields only for proper dict/set lookups."""
        return hash((self.node_id, self.node_type, self.widget_index, self.widget_value))

@dataclass
class WorkflowDependencies:
    """Complete workflow dependency analysis results."""
    workflow_name: str
    found_models: list[WorkflowNodeWidgetRef] = field(default_factory=list)
    builtin_nodes: list[WorkflowNode] = field(default_factory=list)
    non_builtin_nodes: list[WorkflowNode] = field(default_factory=list)

    @property
    def total_models(self) -> int:
        """Total number of model references found."""
        return len(self.found_models) + len(self.found_models)

@dataclass
class ResolvedNodePackage:
    """A potential match for an unknown node."""
    node_type: str
    match_type: str  # "exact", "type_only", "fuzzy", "optional", "manual"
    package_id: str | None = None
    package_data: GlobalNodePackage | None = None
    versions: list[str] | None = None
    match_confidence: float = 1.0
    is_optional: bool = False
    rank: int | None = None  # Popularity rank from registry (1 = most popular)

    def __repr__(self) -> str:
        """Concise representation showing resolution details."""
        version_str = f"{len(self.versions)} version(s)" if self.versions else "no versions"
        rank_str = f", rank={self.rank}" if self.rank else ""
        return f"ResolvedNodePackage(package={self.package_id!r}, node={self.node_type!r}, match={self.match_type}, confidence={self.match_confidence:.2f}, {version_str}{rank_str})"

@dataclass
class ResolvedModel:
    """A potential match for a model reference in a workflow"""
    workflow: str # Resolved models are always associated with a workflow
    reference: WorkflowNodeWidgetRef # Reference to the model in the workflow
    resolved_model: ModelWithLocation | None = None
    model_source: str | None = None # path or URL
    is_optional: bool = False
    match_type: str | None = None  # "exact", "case_insensitive", "filename", "ambiguous", "not_found", "download_intent"
    match_confidence: float = 1.0  # 1.0 = exact, 0.5 = fuzzy
    target_path: Path | None = None  # Where user intends to download model to (for download_intent match_type)
    needs_path_sync: bool = False  # True if workflow path differs from resolved path

    # Category mismatch detection (model in wrong directory for loader node)
    has_category_mismatch: bool = False  # True if model is in wrong directory for node type
    expected_categories: list[str] = field(default_factory=list)  # e.g., ["loras"]
    actual_category: str | None = None  # e.g., "checkpoints"

    @property
    def name(self) -> str:
        return self.reference.widget_value

    @property
    def is_resolved(self) -> bool:
        return self.resolved_model is not None or self.model_source is not None

@dataclass
class DownloadResult:
    """Result of a single model download attempt."""
    success: bool
    filename: str
    model: ModelWithLocation | None = None
    error: str | None = None
    reused: bool = False

@dataclass
class ResolutionResult:
    """Result of resolution check or application."""
    workflow_name: str
    nodes_resolved: list[ResolvedNodePackage] = field(default_factory=list)  # Nodes resolved/added
    nodes_unresolved: list[WorkflowNode] = field(default_factory=list)  # Nodes not found
    nodes_ambiguous: list[list[ResolvedNodePackage]] = field(default_factory=list)  # Nodes with multiple matches
    models_resolved: list[ResolvedModel] = field(default_factory=list)  # Models resolved (or candidates)
    models_unresolved: list[WorkflowNodeWidgetRef] = field(default_factory=list)  # Models not found
    models_ambiguous: list[list[ResolvedModel]] = field(default_factory=list)  # Models with multiple matches
    download_results: list[DownloadResult] = field(default_factory=list)  # Results from model downloads

    @property
    def has_issues(self) -> bool:
        """Check if there are any unresolved issues."""
        return bool(
            self.models_unresolved
            or self.models_ambiguous
            or self.nodes_unresolved
            or self.nodes_ambiguous
        )

    @property
    def has_download_intents(self) -> bool:
        """Check if any models have download intents pending.

        Includes both:
        - download_intent: from pyproject.toml (previously saved download intent)
        - property_download_intent: from node properties (auto-detected URL)
        """
        return any(
            m.match_type in ("download_intent", "property_download_intent")
            for m in self.models_resolved
        )

    @property
    def summary(self) -> str:
        """Generate summary of resolution."""
        parts = []
        if self.nodes_resolved:
            parts.append(f"{len(self.nodes_resolved)} nodes")
        if self.nodes_unresolved:
            parts.append(f"{len(self.nodes_unresolved)} unresolved nodes")
        if self.nodes_ambiguous:
            parts.append(f"{len(self.nodes_ambiguous)} ambiguous nodes")
        if self.models_resolved:
            parts.append(f"{len(self.models_resolved)} models")
        if self.models_unresolved:
            parts.append(f"{len(self.models_unresolved)} unresolved models")
        if self.models_ambiguous:
            parts.append(f"{len(self.models_ambiguous)} ambiguous models")

        return f"Resolutions: {', '.join(parts)}" if parts else "No resolutions"


@dataclass
class CommitAnalysis:
    """Analysis of all workflows for commit."""
    workflows_copied: dict[str, str] = field(default_factory=dict)  # name -> status
    analyses: list[WorkflowDependencies] = field(default_factory=list)
    has_git_changes: bool = False  # Whether there are actual git changes to commit

    @property
    def summary(self) -> str:
        """Generate commit summary."""
        copied_count = len([s for s in self.workflows_copied.values() if s == "copied"])
        if copied_count:
            return f"Update {copied_count} workflow(s)"
        return "Update workflows"


# Status System Dataclasses

@dataclass
class WorkflowSyncStatus:
    """File-level sync status between ComfyUI and .cec."""
    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    synced: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Check if there are any file changes."""
        return bool(self.new or self.modified or self.deleted)

    @property
    def is_synced(self) -> bool:
        """Check if all workflows are synced (no pending changes)."""
        return not self.has_changes

    @property
    def total_count(self) -> int:
        """Total number of workflows."""
        return len(self.new) + len(self.modified) + len(self.deleted) + len(self.synced)


@dataclass
class WorkflowAnalysisStatus:
    """Complete analysis for a single workflow including dependencies and resolution."""
    name: str
    sync_state: str  # "new", "modified", "deleted", "synced"

    # Analysis results
    dependencies: WorkflowDependencies
    resolution: ResolutionResult

    # Installation status (for CLI display without pyproject access)
    uninstalled_nodes: list[str] = field(default_factory=list)  # Node IDs needing installation

    @property
    def has_issues(self) -> bool:
        """Check if workflow has unresolved issues or pending download intents.

        Includes:
        - Unresolved/ambiguous nodes and models
        - Pending download intents (both download_intent and property_download_intent)
        - Category mismatches (model in wrong directory for loader)

        Note: Path sync issues are NOT included here as they're auto-fixable
        and don't prevent commits. They're tracked separately via has_path_sync_issues.
        """
        has_category_mismatch = any(
            m.has_category_mismatch for m in self.resolution.models_resolved
        )
        return (
            self.resolution.has_issues
            or bool(self.uninstalled_nodes)
            or self.resolution.has_download_intents
            or has_category_mismatch
        )

    @property
    def issue_summary(self) -> str:
        """Human-readable summary of all issues that make has_issues=True.

        Invariant: if has_issues is True, this must NOT return "No issues".
        Note: path sync issues are intentionally excluded (auto-fixable, not in has_issues).
        """
        parts = []

        # Resolution blocking issues
        if self.resolution.models_ambiguous:
            parts.append(f"{len(self.resolution.models_ambiguous)} ambiguous models")
        if self.resolution.models_unresolved:
            parts.append(f"{len(self.resolution.models_unresolved)} unresolved models")
        if self.resolution.nodes_unresolved:
            parts.append(f"{len(self.resolution.nodes_unresolved)} missing nodes")
        if self.resolution.nodes_ambiguous:
            parts.append(f"{len(self.resolution.nodes_ambiguous)} ambiguous nodes")

        # Actionable issues (these also trigger has_issues=True)
        if self.uninstalled_nodes:
            parts.append(f"{len(self.uninstalled_nodes)} packages to install")
        if self.download_intents_count > 0:
            parts.append(f"{self.download_intents_count} pending downloads")

        # Category mismatch (model in wrong directory for loader)
        category_mismatch_count = sum(
            1 for m in self.resolution.models_resolved if m.has_category_mismatch
        )
        if category_mismatch_count > 0:
            parts.append(f"{category_mismatch_count} models in wrong directory")

        return ", ".join(parts) if parts else "No issues"

    @property
    def model_count(self) -> int:
        """Total number of model references."""
        return len(self.dependencies.found_models)

    @property
    def node_count(self) -> int:
        """Total number of nodes in workflow."""
        return len(self.dependencies.builtin_nodes) + len(self.dependencies.non_builtin_nodes)

    @property
    def models_resolved_count(self) -> int:
        """Number of successfully resolved models."""
        return len(self.resolution.models_resolved)

    @property
    def nodes_resolved_count(self) -> int:
        """Number of successfully resolved nodes."""
        return len(self.resolution.nodes_resolved)

    @property
    def uninstalled_count(self) -> int:
        """Number of nodes that need installation."""
        return len(self.uninstalled_nodes)

    @property
    def download_intents_count(self) -> int:
        """Number of models queued for download.

        Includes both download_intent and property_download_intent match types.
        """
        return sum(
            1 for m in self.resolution.models_resolved
            if m.match_type in ("download_intent", "property_download_intent")
        )

    @property
    def models_needing_path_sync_count(self) -> int:
        """Number of models that resolved but have wrong paths in workflow JSON."""
        return sum(1 for m in self.resolution.models_resolved if m.needs_path_sync)

    @property
    def has_path_sync_issues(self) -> bool:
        """Check if workflow has model paths that need syncing."""
        return self.models_needing_path_sync_count > 0

    @property
    def models_with_category_mismatch_count(self) -> int:
        """Number of models in wrong category directory for their loader."""
        return sum(1 for m in self.resolution.models_resolved if m.has_category_mismatch)

    @property
    def has_category_mismatch_issues(self) -> bool:
        """Check if workflow has models in wrong category directories."""
        return self.models_with_category_mismatch_count > 0


@dataclass
class DetailedWorkflowStatus:
    """Complete status for all workflows in environment."""
    sync_status: WorkflowSyncStatus
    analyzed_workflows: list[WorkflowAnalysisStatus] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        """Count of workflows with issues."""
        return sum(1 for w in self.analyzed_workflows if w.has_issues)

    @property
    def workflows_with_issues(self) -> list[WorkflowAnalysisStatus]:
        """List of workflows that have unresolved issues."""
        return [w for w in self.analyzed_workflows if w.has_issues]

    @property
    def total_unresolved_models(self) -> int:
        """Total count of unresolved/ambiguous models across all workflows."""
        return sum(
            len(w.resolution.models_unresolved) + len(w.resolution.models_ambiguous)
            for w in self.analyzed_workflows
        )

    @property
    def total_missing_nodes(self) -> int:
        """Total count of missing/ambiguous nodes across all workflows."""
        return sum(
            len(w.resolution.nodes_unresolved) + len(w.resolution.nodes_ambiguous)
            for w in self.analyzed_workflows
        )

    @property
    def is_commit_safe(self) -> bool:
        """Check if safe to commit without issues."""
        return not any(w.has_issues for w in self.analyzed_workflows)
