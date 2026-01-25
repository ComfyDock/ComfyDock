# Workflow Resolution

How ComfyGit resolves workflow dependencies: node mapping and model finding strategies.

## Table of Contents
- [Overview](#overview)
- [Workflow Parsing](#workflow-parsing)
- [Node Resolution](#node-resolution)
- [Model Resolution](#model-resolution)
- [Caching Strategy](#caching-strategy)
- [Interactive Resolution](#interactive-resolution)

---

## Overview

When a workflow is synced, ComfyGit:
1. Parses the workflow JSON to extract dependencies
2. Resolves unknown nodes to registry packages
3. Resolves model references to local files or download URLs
4. Installs missing nodes
5. Downloads missing models
6. Updates pyproject.toml with resolution results

**Key files:**
- `analyzers/workflow_dependency_parser.py` - Parsing
- `resolvers/global_node_resolver.py` - Node resolution
- `resolvers/model_resolver.py` - Model resolution
- `managers/workflow_manager.py` - Orchestration

---

## Workflow Parsing

### Node Classification

**WorkflowDependencyParser** classifies nodes as builtin or custom:

```python
result = parser.analyze_dependencies(workflow_path)
# Returns: WorkflowDependencies
#   - builtin_nodes: list[WorkflowNode]
#   - non_builtin_nodes: list[WorkflowNode]
#   - found_models: list[WorkflowNodeWidgetRef]
```

**Builtin detection:**
- Loads from `.cec/comfyui_builtins.json` (environment-specific)
- Falls back to static config if missing
- Compares `node.type` against builtin set

### Model Extraction

Models extracted from workflows via 4-stage priority:

1. **Properties metadata** (preferred)
   - `node.properties.models` array with URLs and directories
   - Best source - includes download information

2. **Multi-model widget configs**
   - Explicit widget indices for nodes that load multiple models
   - `MULTI_MODEL_WIDGET_CONFIGS` constant

3. **Standard single-model loaders**
   - `CheckpointLoader`, `LoraLoader`, etc.
   - Uses `model_config.is_model_loader_node()`

4. **Pattern matching** (fallback)
   - Fuzzy heuristics for custom nodes
   - File extension matching (`.safetensors`, `.ckpt`, etc.)

**Result structure:**
```python
@dataclass
class WorkflowNodeWidgetRef:
    node_id: str
    widget_value: str      # Filename like "sd_xl.safetensors"
    node_type: str         # "CheckpointLoaderSimple"
    widget_index: int
    property_url: str | None      # If from properties.models
    property_directory: str | None
```

---

## Node Resolution

### Resolution Pipeline

**GlobalNodeResolver** resolves workflow nodes to packages:

```python
packages = resolver.resolve_single_node_with_context(node, context)
```

**4-Stage Priority:**

1. **Custom mappings** (highest priority)
   - Stored in `pyproject.toml` under `custom_node_map`
   - User-confirmed mappings from previous interactive resolutions
   - Can be `False` to mark node as optional

2. **Properties field**
   - `node.properties.cnr_id` - ComfyUI Registry ID
   - `node.properties.ver` - Git commit hash
   - Validates package exists in registry

3. **Global mapping table** (exact match)
   - Uses `create_node_key(node_type, input_signature)`
   - Input signature = sorted list of input names
   - Returns ranked list sorted by popularity

4. **Type-only matching** (fallback)
   - Uses `create_node_key(node_type, "_")`
   - When inputs don't disambiguate

### Ambiguity Handling

When multiple packages match:
- Auto-selection prefers installed packages
- Then picks rank 1 (most popular)
- Otherwise marked as "ambiguous" for user resolution

### Search Function

For interactive resolution, fuzzy search combines:
- SequenceMatcher similarity (0.0-1.0)
- Hint pattern detection: `Node (package)`, `Node | Package`
- Installed package boost: +0.10
- GitHub stars on log scale: max +0.04
- Threshold: 0.3 (30% minimum)

---

## Model Resolution

### Resolution Strategies

**ModelResolver** applies 6 strategies in order:

1. **Context resolution** (confidence: 1.0)
   - Checks pyproject.toml for previous resolutions
   - Handles download intents (`status="unresolved"`)
   - Handles optional models (`criticality="optional"`)

2. **Exact path match** (confidence: 1.0)
   - `relative_path == widget_value`

3. **Reconstructed paths** (confidence: 0.9)
   - For builtin loaders (CheckpointLoader, LoraLoader)
   - Rebuilds full path: `checkpoints/model.ckpt`
   - Uses `model_config.reconstruct_model_path()`

4. **Case-insensitive match** (confidence: 0.8)
   - Path comparison ignoring case
   - Returns multiple if ambiguous

5. **Filename-only match** (confidence: 0.7)
   - Just the filename without directory
   - Last resort for local matching

6. **Property-based download intent** (confidence: 1.0)
   - Creates download intent from `ref.property_url`
   - Uses `property_directory` or infers from node type

### Model Categories

Standard directories:
- `checkpoints` - Base models (SDXL, SD1.5)
- `vae` - Variational autoencoders
- `loras` - LoRA adapters
- `text_encoders` - CLIP models
- `controlnet` - ControlNet models
- `embeddings` - Textual inversion
- `upscale_models` - Upscalers
- `clip_vision` - CLIP vision encoders

**Directory inference from node type:**
```python
NODE_DIRECTORY_MAPPINGS = {
    "CheckpointLoader": ["checkpoints"],
    "LoraLoader": ["loras"],
    "VAELoader": ["vae"],
    ...
}
```

---

## Caching Strategy

### Workflow Cache

SQLite cache (`comfygit_cache/workflows.db`) stores:
- Parsed workflow analysis
- Resolution results
- Per-workflow metadata

**Cache invalidation triggers:**
- Workflow file modified (mtime check)
- pyproject.toml modified (hash check)
- Download intent created
- Model path updated

### Cache Hit Behavior

1. **Full cache hit:** Return cached resolution
2. **Partial hit:** Re-resolve only changed parts
3. **Miss:** Full analysis and resolution

### Progressive Writing

Results written immediately to survive Ctrl+C:
- Node mappings → `pyproject.toml` `custom_node_map`
- Model resolutions → `pyproject.toml` workflow models
- Workflow JSON updates → Batch at end of resolution

---

## Interactive Resolution

### Node Resolution Flow

```
User: "workflow resolve my_workflow.json"

1. Parse workflow → Find unknown nodes
2. For each unknown node:
   a. Search registry for matches
   b. If multiple matches:
      "🔍 Found 3 matches for 'MyCustomNode':
        1. package-a - Description...
        2. package-b - Description...
        3. package-c - Description...

        [1-3] - Select package
        [m]   - Manually enter ID
        [o]   - Mark as optional
        [s]   - Skip"
   c. If no matches:
      "⚠️ Node not found: MyCustomNode
       🔍 Searching...

        [1-5] - Select from search
        [r]   - Refine search
        [m]   - Manual entry
        [o]   - Optional
        [s]   - Skip"
3. Save mapping to custom_node_map
4. Install selected packages
```

### Model Resolution Flow

```
1. For each unresolved model:
   a. Search indexed models
   b. If multiple matches:
      "🔍 Multiple matches for model in node #123:
        Looking for: sd_xl.safetensors
        Found:
        1. checkpoints/sd_xl_base.safetensors (6.9 GB)
        2. checkpoints/sd_xl_refiner.safetensors (6.0 GB)

        [1-2] - Select model
        [o]   - Mark as optional
        [s]   - Skip"
   c. If no matches:
      "⚠️ Model not found: sd_xl.safetensors

        [r] - Refine search
        [d] - Download from URL
        [o] - Mark as optional
        [s] - Skip"
2. If download selected:
   "Enter download URL: "
   "Model will be downloaded to: checkpoints/sd_xl.safetensors
    [Y] Continue  [m] Change path  [b] Back"
3. Queue download intent
4. Execute downloads in batch
```

### Resolution Persistence

**Node mappings** stored in pyproject.toml:
```toml
[tool.comfygit.workflows."my_workflow.json"]
custom_node_map = {
    "MyCustomNode" = "package-id",
    "OptionalNode" = false  # Marked optional
}
```

**Model resolutions** stored per-workflow:
```toml
[tool.comfygit.workflows."my_workflow.json".models]
"sd_xl.safetensors" = {
    hash = "abc123",
    status = "resolved",
    criticality = "required",
    nodes = [...]
}
```

---

## Deduplication

### Node Deduplication

Same node type in multiple workflow nodes → Prompt once, apply to all.

### Model Deduplication

Same filename in same loader type → Prompt once, apply to all refs.

All node refs written together:
```toml
[tool.comfygit.workflows."workflow.json".models]
"model.safetensors" = {
    nodes = [
        { node_id = "1", widget_index = 0 },
        { node_id = "5", widget_index = 0 }
    ]
}
```

---

## Troubleshooting

### "Node not found in registry"

1. Check node name spelling
2. Try refining search with package name hint
3. Enter GitHub URL manually
4. Mark as optional if not critical

### "Model not found"

1. Check models directory location: `cg model index status`
2. Scan for new models: `cg model index sync`
3. Download if missing: Enter URL when prompted
4. Check file exists in expected category directory

### "Ambiguous model match"

Multiple models with same filename:
1. Select the correct one from list
2. Consider renaming to avoid future ambiguity
3. Model hash will be tracked to prevent re-prompting
