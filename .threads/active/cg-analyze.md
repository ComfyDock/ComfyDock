---
schema_version: 1
id: cg-analyze
title: "cg analyze \u2014 Offline Workflow Resolution"
status: active
priority: 1
created_at: '2026-03-04T07:00:19Z'
updated_at: '2026-03-04T07:03:28Z'
---

## Tasks
- [ ] cg-analyze.0 Fix total_models double-count bug in WorkflowDependencies {priority=1 notes="## Bug
`WorkflowDependencies.total_models` at `packages/core/src/comfygit_core/models/workflow.py:666-668` returns:
```python
return len(self.found_models) + len(self.found_models)
```
This is a clear 2x overcount. Should be:
```python
return len(self.found_models)
```
- [ ] cg-analyze.1 Add workflow input normalization layer (UI + API format detection) {priority=1 deps=[cg-analyze.0] notes="## Goal
Create a normalization function in core that detects whether a workflow JSON is in UI format or API format, and normalizes both to the internal Workflow model.
- [ ] cg-analyze.2 Extract resolution logic from WorkflowManager into standalone service {priority=1 deps=[cg-analyze.1] notes="## Goal
Extract the core resolution logic from `WorkflowManager.resolve_workflow()` into a standalone, reusable service that can operate WITHOUT an environment context. This is the most critical architectural task — do NOT build a parallel resolver.
- [ ] cg-analyze.3 Add workflow analysis orchestration service (report assembly) {priority=1 deps=[cg-analyze.2] notes="## Goal
Create the top-level analysis orchestration service that ties together parsing, classification, resolution, and report generation into a single callable function. This is the core library entry point that both `cg analyze` CLI and a future web API will consume.
- [ ] cg-analyze.4 Add cg analyze top-level CLI command {priority=1 deps=[cg-analyze.3] notes="## Goal
Add `cg analyze <workflow.json>` as a new top-level CLI command that takes a raw workflow file and outputs a human-readable resolution report with optional JSON/TOML output.
- [ ] cg-analyze.5 Add optional provider-backed model source lookup (--online mode) {priority=2 deps=[cg-analyze.4] notes="## Goal
Add an optional online mode to `cg analyze` that uses deterministic API lookups (CivitAI, HuggingFace) to discover model download URLs for models that can't be resolved offline. This is Phase 2 — the offline analysis (tasks 0-4) should work first.

## Why This Matters
For random internet workflows without embedded model metadata, offline model URL discovery is weak (35-65%). Online provider lookups can significantly improve this without resorting to LLM-based guessing.

## Provider Lookup Priority Chain
1. **Exact hash match** — local model index (already in offline path)
2. **Embedded URL** — from workflow `properties.models` metadata (already in offline path)
3. **Exact filename + expected category** — local index (already in offline path)
4. **CivitAI API by hash** — `CivitAIClient.get_model_by_hash()` (NEW integration)
5. **CivitAI API search by filename** — `CivitAIClient.search_models()` (NEW integration)
6. **HuggingFace API search** — `list_models(search=...)`, `list_repo_files()` (NEW integration)
7. **Unresolved** — flag for manual resolution or LLM agent

## Existing Code to Leverage
- `packages/core/src/comfygit_core/clients/civitai_client.py` — already has:
  - `search_models(query)` — search by name
  - `get_model(model_id)` — get model details
  - `get_model_version(version_id)` — get specific version
  - `get_model_by_hash(hash)` — lookup by hash
  - Rate limit handling (429), auth handling (401/403)
  - API key support via workspace config
  
- `packages/core/src/comfygit_core/services/huggingface_url.py` — URL parsing/handling
- `packages/core/src/comfygit_core/services/model_downloader.py` — understands HF URLs, suggests target paths

## Practical Concerns (from Codex review)
- **CivitAI rate limits**: client already handles 429 responses; may need to batch/throttle for workflows with many models
- **CivitAI auth**: some model downloads require API key; client already reads from workspace config (`workspace_config_repository.py:119`)
- **HuggingFace**: current code expects direct file URLs; repo URLs are rejected in downloader path (`model_downloader.py:269`). Need to handle repo-level search → file URL construction
- **HuggingFace auth**: some repos are gated; need HF token support (workspace config already has `hf_token` field at `workspace_config_repository.py:179`)
- **False positives**: filename-based search can return wrong models (e.g., 'model.safetensors' is too generic). Need confidence scoring based on filename specificity

## CLI Integration
```
cg analyze <workflow.json> --online    # Enable provider lookups
cg analyze <workflow.json>             # Default: offline only (fast, no network)
```

When --online is used:
- After offline resolution, collect unresolved models
- For each unresolved model, try provider lookup chain
- Report results with provenance: 'civitai_hash', 'civitai_search', 'huggingface_search'
- Show confidence level for each online match

## Implementation

### New: Model Source Lookup Service
Create `packages/core/src/comfygit_core/services/model_source_lookup.py`:

```python
class ModelSourceLookupService:
    \"\"\"Deterministic model source discovery via provider APIs.\"\"\"
    
    def __init__(
        self,
        civitai_client: CivitAIClient | None = None,
        hf_token: str | None = None,
    ):
        ...
    
    def lookup(self, filename: str, hash: str | None = None, 
               node_type: str | None = None) -> ModelSourceResult | None:
        \"\"\"Try provider APIs to find download URL for a model.\"\"\"
        # 1. CivitAI by hash (highest confidence)
        # 2. CivitAI search by filename (medium confidence)
        # 3. HuggingFace search (lower confidence for common names)
        ...
```

### Integrate into WorkflowAnalysisService
Add optional `online_lookup` parameter to `analyze()`:
```python
def analyze(self, workflow_path: Path, online: bool = False) -> AnalysisReport:
    report = self._offline_analyze(workflow_path)
    if online and report.models_without_sources > 0:
        self._enrich_with_online_lookups(report)
    return report
```

## Files
- NEW: `packages/core/src/comfygit_core/services/model_source_lookup.py`
- MODIFY: `packages/core/src/comfygit_core/services/workflow_analysis_service.py` — add online enrichment
- MODIFY: `packages/cli/comfygit_cli/cli.py` — add --online flag
- MODIFY: `packages/cli/comfygit_cli/global_commands.py` — pass online flag
- REFERENCE: `packages/core/src/comfygit_core/clients/civitai_client.py`
- REFERENCE: `packages/core/src/comfygit_core/services/huggingface_url.py`
- REFERENCE: `packages/core/src/comfygit_core/repositories/workspace_config_repository.py` — API key config

## Testing
- Test CivitAI hash lookup with known model hash
- Test CivitAI search with specific filename
- Test HuggingFace search integration
- Test with no API keys configured (graceful degradation)
- Test rate limit handling
- Test with generic filenames (should return low confidence or skip)
- Test full pipeline: offline analysis → online enrichment → merged report"}

## CLI Design

```
cg analyze <workflow.json> [options]

Arguments:
  workflow.json          Path to ComfyUI workflow JSON file (UI or API format)

Options:
  --json                 Output as machine-readable JSON (for CI/tooling)
  --draft-spec           Also output a draft pyproject.toml fragment
  --verbose              Show detailed provenance for each resolved item
  --quiet                Only show unresolved/actionable items
```

## Key Requirement: No Workspace Required
This command MUST work without `cg init`. Use `get_workspace_optional()` (already exists in `cli_utils.py`):
- If workspace exists: use its cached registry data and model index for richer results
- If no workspace: fetch registry data to temp location, skip model index lookups

## Command Registration
Add to `packages/cli/comfygit_cli/cli.py` in `_add_global_commands()`:
```python
analyze_parser = subparsers.add_parser('analyze', help='Analyze a workflow file for dependencies')
analyze_parser.add_argument('workflow', type=Path, help='Path to workflow JSON file')
analyze_parser.add_argument('--json', action='store_true', help='Output as JSON')
analyze_parser.add_argument('--draft-spec', action='store_true', help='Output draft pyproject.toml')
analyze_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed provenance')
analyze_parser.add_argument('--quiet', '-q', action='store_true', help='Only show unresolved items')
analyze_parser.set_defaults(func=global_cmds.analyze)
```

## Handler Implementation
Add `analyze()` method to `GlobalCommands` class in `global_commands.py`:

```python
def analyze(self, args):
    workspace = get_workspace_optional()
    
    if workspace:
        service = WorkflowAnalysisService.create_from_workspace(workspace)
    else:
        service = WorkflowAnalysisService.create_standalone()
    
    report = service.analyze(args.workflow)
    
    if args.json:
        # Output machine-readable JSON
        print(json.dumps(report.to_dict(), indent=2))
    else:
        # Human-readable output
        _render_analysis_report(report, verbose=args.verbose, quiet=args.quiet)
    
    if args.draft_spec:
        _render_draft_spec(report.draft_spec)
```

## Human-Readable Output Format
```
╭─ Workflow Analysis: my-workflow.json ─╮

Format: ComfyUI UI (list-based)
Nodes:  42 total, 15 unique types
Models: 4 references

── Node Resolution ──────────────────────
✓ 12 builtin nodes
✓ 2 custom nodes resolved
  • comfyui-z-image (exact match, registry)
  • comfyui-ace-step (exact match, registry)
⚠ 1 version-gated node
  • NewNodeType — requires ComfyUI >= 1.25.0

── Model Resolution ─────────────────────
✓ 2 models with download URLs (from workflow metadata)
  • z_image_turbo_bf16.safetensors → huggingface.co/...
  • qwen_3_4b.safetensors → huggingface.co/...
⚠ 1 model without source
  • custom_lora.safetensors — no download URL found
✓ 1 model resolved from local index
  • ae.safetensors → hash matched

── Summary ──────────────────────────────
Node resolution:  93% (14/15)
Model resolution: 75% (3/4)
Confidence: medium

1 action needed:
  • custom_lora.safetensors: Add download URL with 'cg model add-source'

╰────────────────────────────────────────╯
```

## JSON Output Schema
```json
{
  \"workflow_name\": \"my-workflow\",
  \"input_format\": \"ui_list\",
  \"nodes\": {
    \"total\": 42,
    \"unique_types\": 15,
    \"builtin\": 12,
    \"resolved\": [{\"node_type\": \"...\", \"package_id\": \"...\", \"match_type\": \"exact\"}],
    \"version_gated\": [{\"node_type\": \"...\", \"message\": \"...\"}],
    \"unresolved\": [{\"node_type\": \"...\"}],
    \"ambiguous\": [{\"node_type\": \"...\", \"candidates\": [...]}]
  },
  \"models\": {
    \"total_refs\": 4,
    \"resolved\": [{\"filename\": \"...\", \"url\": \"...\", \"hash\": \"...\"}],
    \"unresolved\": [{\"filename\": \"...\", \"node_type\": \"...\"}]
  },
  \"confidence\": {
    \"node_rate\": 0.93,
    \"model_rate\": 0.75,
    \"overall\": \"medium\"
  },
  \"draft_spec\": { ... },
  \"actions_needed\": [...]
}
```

## Files
- MODIFY: `packages/cli/comfygit_cli/cli.py` — add analyze subparser
- MODIFY: `packages/cli/comfygit_cli/global_commands.py` — add analyze handler
- NEW: `packages/cli/comfygit_cli/formatters/analyze_formatter.py` (optional — if output rendering is complex enough to warrant its own module)
- USES: `packages/core/src/comfygit_core/services/workflow_analysis_service.py` (from cg-analyze.3)
- USES: `packages/cli/comfygit_cli/cli_utils.py` — get_workspace_optional()

## Testing
- Test CLI invocation with a real workflow JSON file
- Test --json output is valid JSON matching schema
- Test --draft-spec output
- Test without workspace (standalone mode)
- Test with workspace (enhanced mode)
- Test with nonexistent file (error handling)
- Test with malformed JSON (error handling)"}

## Architecture
Location: `packages/core/src/comfygit_core/services/workflow_analysis_service.py`

This service orchestrates the full pipeline:
1. Normalize input (UI/API format detection via workflow_input.py from task cg-analyze.1)
2. Parse workflow (`WorkflowDependencyParser.analyze_dependencies()`)
3. Resolve dependencies (`WorkflowResolutionService.resolve()` from task cg-analyze.2)
4. Build analysis report with confidence/provenance
5. Generate draft environment spec (pyproject.toml fragment)

## Report Model
Create a thin `AnalysisReport` that wraps existing models:

```python
@dataclass
class AnalysisReport:
    \"\"\"Complete analysis of a raw workflow file.\"\"\"
    
    # Input metadata
    workflow_name: str
    input_format: str  # 'ui_list', 'ui_dict', 'api', 'api_wrapped'
    total_nodes: int
    total_unique_node_types: int
    
    # Node analysis
    builtin_nodes: list[WorkflowNode]
    version_gated_nodes: list[WorkflowNode]
    
    # Resolution results (reuse existing ResolutionResult)
    resolution: ResolutionResult
    
    # Model analysis
    total_model_refs: int
    models_with_embedded_urls: int  # from properties.models
    models_without_sources: int
    
    # Draft environment spec
    draft_spec: dict  # pyproject.toml-compatible structure
    
    # Confidence summary
    node_resolution_rate: float  # 0.0-1.0
    model_resolution_rate: float  # 0.0-1.0
    overall_confidence: str  # 'high', 'medium', 'low', 'incomplete'
    
    # Actionable guidance
    unresolved_items: list[dict]  # [{type, name, suggestion, next_action}]
```

## Provenance/Confidence
Leverage EXISTING match types — do not invent new ones:
- Node matches: `exact`, `type_only`, `properties`, `properties_upgraded`, `custom_mapping`, `fuzzy`
- Model flows: `download_intent`, `property_download_intent`
- Manager-only/synthetic matches: surface as `uninstallable` with explicit warning

Confidence tiers:
- **high**: exact/properties match with download URL
- **medium**: type_only match or model without URL but with hash
- **low**: fuzzy match or unresolvable model
- **unresolved**: no match found

## Draft Spec Generation
Generate a partial `pyproject.toml` structure that could be used to create a ComfyGit environment:

```toml
[tool.comfygit]
comfyui_version = \"latest\"  # or detected from version-gated nodes

[tool.comfygit.nodes]
# Resolved custom node packages
\"package-id\" = {version = \"1.0.0\", source = \"registry\"}

[tool.comfygit.workflows.\"workflow-name\".models]
# Resolved model references
[[tool.comfygit.workflows.\"workflow-name\".models]]
filename = \"model.safetensors\"
hash = \"...\"  # if available
sources = [\"https://...\"]  # if available
status = \"resolved\"  # or \"unresolved\"
```

## Service Interface

```python
class WorkflowAnalysisService:
    \"\"\"Analyze raw workflow files without requiring an environment.\"\"\"
    
    def __init__(
        self,
        node_mappings_repository: NodeMappingsRepository | None = None,
        model_repository: ModelRepository | None = None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None,
    ):
        \"\"\"All dependencies optional — degrades gracefully.\"\"\"
        ...
    
    @classmethod
    def create_standalone(cls, cache_dir: Path | None = None) -> 'WorkflowAnalysisService':
        \"\"\"Factory for standalone use (no workspace). Sets up temp registry cache.\"\"\"
        ...
    
    @classmethod
    def create_from_workspace(cls, workspace) -> 'WorkflowAnalysisService':
        \"\"\"Factory for workspace-aware use. Uses workspace's cached mappings and model index.\"\"\"
        ...
    
    def analyze(self, workflow_path: Path) -> AnalysisReport:
        \"\"\"Full analysis pipeline: parse → classify → resolve → report.\"\"\"
        ...
    
    def analyze_json(self, data: dict, name: str = 'unnamed') -> AnalysisReport:
        \"\"\"Analyze from parsed JSON dict.\"\"\"
        ...
```

## Graceful Degradation
When running without workspace:
- No `NodeMappingsRepository`: attempt to fetch registry data to temp cache; if offline, report 'registry unavailable' and skip node resolution
- No `ModelRepository`: skip model index lookups, only use embedded URLs from workflow metadata
- No `builtin_versions_repository`: fall back to static 481-node builtin config (slightly less accurate version-gating)

## Files
- NEW: `packages/core/src/comfygit_core/services/workflow_analysis_service.py`
- USES: `packages/core/src/comfygit_core/services/workflow_input.py` (from cg-analyze.1)
- USES: `packages/core/src/comfygit_core/services/workflow_resolution_service.py` (from cg-analyze.2)
- USES: `packages/core/src/comfygit_core/analyzers/workflow_dependency_parser.py`
- USES: `packages/core/src/comfygit_core/models/workflow.py` (WorkflowDependencies, ResolutionResult)
- REFERENCE: `packages/core/src/comfygit_core/services/registry_data_manager.py` — for standalone cache setup

## Testing
- Test full pipeline with a real workflow JSON (use Z-Image workflow from test fixtures if available)
- Test standalone mode (no workspace) — verify graceful degradation
- Test workspace mode — verify it uses cached data
- Test with workflow containing embedded model URLs — verify they appear in report
- Test with workflow containing unknown custom nodes — verify unresolved items
- Test draft spec output format"}

## Why Extract, Not Build Parallel
Both Codex (GPT-5.3) and Oracle (GPT-5.2 Pro) agree: `WorkflowManager.resolve_workflow()` already contains the full resolution pipeline (node→package mapping, ambiguity detection, model resolution, confidence/provenance). Building a parallel `WorkflowAnalyzer` would create a second resolver that drifts from the real one. Instead, extract the reusable core.

## Current State of resolve_workflow()
Location: `packages/core/src/comfygit_core/managers/workflow_manager.py:819-1035`

**Reusable core (extract this):**
- Deduplicate nodes by type (prefer nodes with properties/cnr_id)
- Resolve each unique node via `GlobalNodeResolver.resolve_single_node_with_context()`
- Classify results: resolved / version_gated / uninstallable / unresolved / ambiguous
- Build node_guidance dict
- Deduplicate model refs by (widget_value, node_type)
- Resolve each model via `ModelResolver.resolve_model()`
- Classify: resolved / unresolved / ambiguous
- Return `ResolutionResult`

**Environment-coupled reads (need adapter/defaults):**
- `self.pyproject.nodes.get_existing()` → installed packages (default: empty dict for standalone)
- `self.pyproject.workflows.get_custom_node_map(workflow_name)` → custom mappings (default: empty dict)
- `self.pyproject.workflows.get_workflow_models(workflow_name)` → previous model resolutions (default: empty list)
- `self.pyproject.models.get_all()` → global models table (default: empty list)
- `self.cec_path` → for NodeClassifier (default: None, uses static fallback)
- `self.builtin_versions_repository` → version-gated builtins (default: None)

**Environment-specific mutations (stay in WorkflowManager):**
- `fix_resolution()` / `apply_resolution()` — writes to pyproject.toml
- `update_workflow_model_paths()` — syncs model paths
- Workflow cache operations
- Download coordination

## Implementation Plan

### Step 1: Create the standalone service
Create `packages/core/src/comfygit_core/services/workflow_resolution_service.py`:

```python
@dataclass
class ResolutionContext:
    \"\"\"Context for standalone resolution (replaces environment state).\"\"\"
    installed_packages: dict[str, NodeInfo] = field(default_factory=dict)
    custom_node_mappings: dict[str, str | bool] = field(default_factory=dict)
    previous_model_resolutions: dict[WorkflowNodeWidgetRef, Any] = field(default_factory=dict)
    global_models: dict[str, Any] = field(default_factory=dict)
    cec_path: Path | None = None
    builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None

class WorkflowResolutionService:
    \"\"\"Standalone workflow resolution — no environment required.\"\"\"
    
    def __init__(
        self,
        global_node_resolver: GlobalNodeResolver,
        model_resolver: ModelResolver,
    ):
        ...
    
    def resolve(
        self,
        analysis: WorkflowDependencies,
        context: ResolutionContext | None = None,
    ) -> ResolutionResult:
        \"\"\"Core resolution logic extracted from WorkflowManager.resolve_workflow().\"\"\"
        ...
```

### Step 2: Make WorkflowManager delegate
Refactor `WorkflowManager.resolve_workflow()` to:
1. Build a `ResolutionContext` from its environment state (pyproject, cec_path, etc.)
2. Call `WorkflowResolutionService.resolve(analysis, context)`
3. Return the result unchanged

This MUST be a no-behavior-change refactor. All existing tests must pass without modification.

### Step 3: Verify
Run the full test suite. The extraction should be invisible to all existing consumers.

## Dependencies
- `GlobalNodeResolver` — only needs `NodeMappingsRepository` (already standalone-capable)
- `ModelResolver` — needs `ModelRepository` (can be created with empty/temp DB for standalone)
- `NodeClassifier` — needs optional `cec_path` (falls back to static 481-node config)
- `ResolutionResult` model — already a pure dataclass, no environment coupling

## Key Constraints
- The extracted service MUST produce identical results to current WorkflowManager.resolve_workflow() when given the same inputs
- No new dependencies on environment-specific code
- WorkflowManager becomes a thin adapter — it should NOT duplicate any resolution logic
- The service should be usable from both WorkflowManager (with full env context) and cg analyze (with minimal/empty context)

## Files
- NEW: `packages/core/src/comfygit_core/services/workflow_resolution_service.py`
- MODIFY: `packages/core/src/comfygit_core/managers/workflow_manager.py` — delegate to new service
- REFERENCE: `packages/core/src/comfygit_core/resolvers/global_node_resolver.py` — node resolution
- REFERENCE: `packages/core/src/comfygit_core/resolvers/model_resolver.py` — model resolution
- REFERENCE: `packages/core/src/comfygit_core/models/workflow.py` — ResolutionResult, WorkflowDependencies

## Testing
- All existing workflow resolution tests must pass unchanged (this is a refactor, not a behavior change)
- Add new tests for standalone service with empty ResolutionContext (no environment)
- Test that WorkflowManager.resolve_workflow() produces identical output before and after refactor"}

## Background
`Workflow.from_json()` currently handles:
- UI format: `{\"nodes\": [...], \"links\": [...]}` (list-based)
- Dict format: `{\"nodes\": {\"1\": {...}, \"2\": {...}}}` (dict-based)
- Subgraphs (ComfyUI v1.24.3+)

It does NOT handle:
- Pure API prompt format: top-level node-id keys with `class_type`, no `\"nodes\"` wrapper
  Example: `{\"1\": {\"class_type\": \"CLIPLoader\", \"inputs\": {...}}, \"2\": {...}}`

## Architecture Decision
Do NOT import `docker/serverless/schema.py` into core — that crosses the package boundary. The serverless schema code is execution-oriented (convert_ui_to_api_format). We need the inverse: detect format and normalize to internal model.

## Implementation
Create `packages/core/src/comfygit_core/services/workflow_input.py` (or similar) with:

```python
def normalize_workflow_input(data: dict) -> Workflow:
    \"\"\"Detect workflow format and normalize to internal Workflow model.
    
    Handles:
    1. UI format (nodes as list with links) -> existing Workflow.from_json()
    2. UI format (nodes as dict) -> existing Workflow.from_json()
    3. API prompt format (top-level node-id keys with class_type) -> wrap and parse
    4. Malformed/partial workflows -> raise descriptive ValueError
    \"\"\"
```

### Format Detection Heuristics
- Has `\"nodes\"` key (list or dict) → UI format → pass to Workflow.from_json()
- Has `\"prompt\"` key wrapping node dict → API format with prompt wrapper
- Top-level keys are numeric strings and values have `\"class_type\"` → naked API format
- Otherwise → malformed, raise with helpful error

### API Format Normalization
For API format, synthesize minimal structure for Workflow.from_json():
- Wrap in `{\"nodes\": {...}}` where each value gets its key as `\"id\"` and `\"class_type\"` mapped to `\"type\"`
- This allows the existing parser to handle it

## Files
- NEW: `packages/core/src/comfygit_core/services/workflow_input.py`
- MODIFY: `packages/core/src/comfygit_core/models/workflow.py` — possibly extend Workflow.from_json() or keep normalization external
- REFERENCE: `docker/serverless/schema.py` — for understanding API format structure (do not import)

## Testing
- Test with UI format workflow JSON (list nodes)
- Test with UI format workflow JSON (dict nodes)
- Test with API prompt format (naked top-level keys)
- Test with API format wrapped in {\"prompt\": {...}}
- Test with malformed JSON (missing class_type, empty, etc.)
- Test with subgraph workflows"}

## Context
Found during Oracle audit (GPT-5.2 Pro, 27min thinking) of the cg analyze architecture review. Confirmed by Codex (GPT-5.3, xhigh).

## Files
- `packages/core/src/comfygit_core/models/workflow.py` line 666-668

## Testing
- Add unit test that creates a WorkflowDependencies with known found_models and asserts total_models equals len(found_models), not 2x.
- Check if total_models is used anywhere else in the codebase that may have been compensating for the bug."}

## Notes
## Epic: cg analyze — Offline Workflow Resolution

### Goal
Add a new `cg analyze` CLI command that takes a raw ComfyUI workflow JSON file and produces a complete dependency resolution report + draft environment spec, WITHOUT requiring a running ComfyUI instance or an existing ComfyGit environment.

### Business Context
RunPod's 'ComfyUI-to-API' tool uses an LLM agent to resolve workflow dependencies. In testing:
- Takes 15+ minutes on complex workflows
- Chokes entirely on moderately complex workflows (never completes)
- No progress feedback — black box
- Uses LLM web searching to guess at dependencies (slow, unreliable)

We want to do this in SECONDS using ComfyGit's structured resolution engine (registry lookups, static configs, hash-based model index). An LLM agent would only be needed for edge cases.

### Architecture (agreed by Codex GPT-5.3 + Oracle GPT-5.2 Pro)
1. Extract resolution logic from `WorkflowManager.resolve_workflow()` into a standalone service — do NOT build a parallel resolver
2. New code lives in `comfygit_core/services/workflow_analysis_service.py` (services layer, not analyzers — this is orchestration)
3. `WorkflowManager` becomes a thin adapter over the new service (no behavior change for existing consumers)
4. `cg analyze` is a new top-level CLI command (not under `cg workflow`)
5. Workspace is optional — if exists, use cached mappings/model index; if not, use temp registry data
6. Do NOT import `docker/serverless/schema.py` into core — build proper normalization layer

### Implementation Order
1. Fix total_models bug
2. Add workflow input normalizer (UI/API format)
3. Extract resolution service from WorkflowManager
4. Add analysis orchestration service (report assembly)
5. Add cg analyze CLI command
6. Optional: provider-backed model lookup (--online mode)

### Key Files
- `packages/core/src/comfygit_core/managers/workflow_manager.py` — resolve_workflow() to extract from
- `packages/core/src/comfygit_core/resolvers/global_node_resolver.py` — node resolution (takes NodeMappingsRepository)
- `packages/core/src/comfygit_core/resolvers/model_resolver.py` — model resolution (takes ModelRepository)
- `packages/core/src/comfygit_core/analyzers/workflow_dependency_parser.py` — workflow parsing (already offline-capable)
- `packages/core/src/comfygit_core/analyzers/node_classifier.py` — builtin vs custom (static fallback with 481 nodes)
- `packages/core/src/comfygit_core/models/workflow.py` — Workflow, WorkflowDependencies, ResolutionResult models
- `packages/core/src/comfygit_core/repositories/node_mappings_repository.py` — offline node registry cache (~15.5MB)
- `packages/core/src/comfygit_core/services/registry_data_manager.py` — registry data caching (24h TTL)
- `packages/core/src/comfygit_core/clients/civitai_client.py` — CivitAI API (search, get_model_by_hash)
- `packages/core/src/comfygit_core/services/huggingface_url.py` — HuggingFace URL handling
- `packages/cli/comfygit_cli/cli.py` — CLI command registration
- `packages/cli/comfygit_cli/cli_utils.py` — has get_workspace_optional() already
- `packages/cli/comfygit_cli/global_commands.py` — global command handlers

### Accuracy Estimates
- Custom node package resolution (offline): 85-95% on mainstream public workflows
- Model resolution with local workspace index: 70-90%
- Model URL discovery for random internet workflow: 35-65%
- With embedded properties.models URLs: much higher for those refs

### Total Effort Estimate: ~700-1,150 LOC (including tests)
