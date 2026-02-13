# Global Node Mappings System

The global node mappings system enables resolution of unknown custom nodes in ComfyUI workflows by maintaining a comprehensive database of node types and their input signatures.

## Overview

When you import a workflow that contains custom nodes you don't have installed, the system can:

1. **Identify unknown nodes** by comparing against builtin ComfyUI nodes
2. **Resolve nodes to packages** using global mappings with input signature matching
3. **Suggest package installations** with optimal version selection
4. **Auto-install suggested packages** (with user confirmation)

## Components

### 1. Global Mappings Builder (`scripts/build_global_mappings.py`)

Scans the ComfyUI registry to build comprehensive node mappings:

```bash
# Build mappings for first 10 packages (testing)
uv run scripts/build_global_mappings.py --limit 10

# Build mappings for specific packages only
uv run scripts/build_global_mappings.py --node-ids comfyui_tinyterranodes comfyui-custom-scripts

# Build single package with limited versions
uv run scripts/build_global_mappings.py --node-ids comfyui_tinyterranodes --max-versions 2

# Fast Testing Mode (Non-Deterministic, 3-5 seconds)
uv run scripts/build_global_mappings.py --pages 1 --node-limit 5

# Fast with broader coverage
uv run scripts/build_global_mappings.py --pages 3 --node-limit 20

# Deterministic Mode (Consistent Results)
uv run scripts/build_global_mappings.py --node-limit 10

# Target specific packages (fastest deterministic)
uv run scripts/build_global_mappings.py --node-ids comfyui_tinyterranodes comfyui-custom-scripts

# Build full mappings (all packages)
uv run scripts/build_global_mappings.py

# Incremental update from existing mappings file
uv run scripts/build_global_mappings.py --input node_mappings.json --node-limit 50

# MVP mode (no input signatures)
uv run scripts/build_global_mappings.py --node-limit 10 --mvp
```

### 2. Global Node Resolver (`src/comfygit_core/services/global_node_resolver.py`)

Service that resolves unknown nodes using the mappings:

```python
from comfygit_core.services.global_node_resolver import GlobalNodeResolver

resolver = GlobalNodeResolver()
result = resolver.resolve_workflow_nodes(unknown_nodes)

for node_type, match in result.resolved.items():
    print(f"{node_type} -> {match.package_id}")
```

### 3. Input Signature Matching

Advanced version resolution using input type signatures:

- **Registry format**: `{"required":{"mask":["MASK"],"scale":["FLOAT"]}}`
- **Workflow format**: `[{"name":"mask","type":"MASK"},{"name":"scale","type":"FLOAT"}]`
- **Normalized**: `mask:MASK|scale:FLOAT`
- **Hashed**: `a3f2b891`
- **Compound key**: `AK_ScaleMask:a3f2b891`

## Usage

### Testing the System

```bash
# Test input signature utilities
uv run scripts/test_signatures.py

# Test resolver with sample nodes
uv run scripts/test_global_resolver.py

# Test resolver with actual workflow
uv run scripts/test_global_resolver.py --workflow path/to/workflow.json

# Show mapping statistics
uv run scripts/test_global_resolver.py --stats
```

### Building Mappings (Development)

```bash
# Start small for testing (2 packages, 2 versions each)
uv run scripts/build_global_mappings.py --limit 2 --max-versions 2

# Test specific packages
uv run scripts/build_global_mappings.py --node-ids comfyui_tinyterranodes --max-versions 2

# Check the output
cat src/comfygit_core/data/node_mappings.json | jq '.stats'

# Test resolver works
uv run scripts/test_global_resolver.py --stats

# Fast Testing (Non-Deterministic, 3-5 seconds)
uv run scripts/build_global_mappings.py --pages 1 --node-limit 2
uv run scripts/build_global_mappings.py --pages 2 --node-limit 5

# Deterministic Testing (Consistent Results)
uv run scripts/build_global_mappings.py --node-limit 10
uv run scripts/build_global_mappings.py --node-ids comfyui_tinyterranodes --max-versions 3

# Production Building
uv run scripts/build_global_mappings.py --node-limit 50
uv run scripts/build_global_mappings.py --node-limit 100

# Daily incremental update (processes only new versions)
uv run scripts/build_global_mappings.py --input node_mappings.json --node-limit 100

# Full registry scan (production - initial run)
uv run scripts/build_global_mappings.py --max-versions 5
```

### Command Options Reference

#### Performance vs Determinism Trade-offs

The script provides flexible options to balance speed vs consistency:

| Option | Speed | Deterministic | Use Case |
|--------|-------|---------------|----------|
| `--pages N` | ⚡ Fast | ❌ No | Quick testing, development |
| `--node-limit N` | 🐌 Slow | ✅ Yes | Production, consistent results |
| `--node-ids` | ⚡⚡ Fastest | ✅ Yes | Targeted updates, debugging |

#### Option Details

- **`--pages N`**: Fetch only first N pages from registry API
  - Pros: Very fast (3-5 seconds for 1 page)
  - Cons: Non-deterministic results across runs
  - Best for: Quick development testing

- **`--node-limit N`**: Fetch ALL nodes, sort, then limit to first N
  - Pros: Deterministic, consistent ordering
  - Cons: Slower (fetches entire registry first)
  - Best for: Production builds, reproducible results

- **`--node-ids package1 package2`**: Target specific packages
  - Pros: Fastest + deterministic
  - Cons: Requires knowing package names
  - Best for: Incremental updates, debugging specific packages

#### Argument Validation

- `--node-ids` and `--pages` are **mutually exclusive**
- `--node-ids` and `--node-limit` are **mutually exclusive**
- `--pages` and `--node-limit` **can be combined** for fast deterministic subsets

#### Recommended Workflows

```bash
# Development: Fast iteration
uv run scripts/build_global_mappings.py --pages 1 --node-limit 3

# Testing: Deterministic but small
uv run scripts/build_global_mappings.py --node-limit 10

# Production: Full deterministic scan
uv run scripts/build_global_mappings.py

# Debugging: Target specific issues
uv run scripts/build_global_mappings.py --node-ids problematic-package
```

### Integration with Workflow Management

The global resolver integrates with the existing workflow system:

```bash
# Track a workflow (will use global mappings for unknown nodes)
comfygit workflow track my_workflow

# The system will:
# 1. Parse workflow for custom nodes
# 2. Check local mappings first
# 3. Fall back to global mappings
# 4. Suggest missing packages to install
```

## Data Structure

The generated mappings file contains:

```json
{
  "version": "2024.12.20",
  "stats": {
    "packages": 523,
    "total_nodes": 15234,
    "signatures": 18922
  },
  "mappings": {
    "CreateVideo:a3f2b891": {
      "package_id": "Kosinkadink/ComfyUI-AnimateDiff-Evolved",
      "versions": ["1.0.0", "1.0.1"],
      "confidence": 1.0
    },
    "CreateVideo:_": {
      "package_id": "Kosinkadink/ComfyUI-AnimateDiff-Evolved",
      "versions": ["*"],
      "confidence": 0.7
    }
  },
  "packages": {
    "Kosinkadink/ComfyUI-AnimateDiff-Evolved": {
      "display_name": "AnimateDiff Evolved",
      "versions": {
        "1.0.0": {"deprecated": false}
      }
    }
  }
}
```

## Resolution Strategies

1. **Exact Match**: Node type + input signature hash
2. **Type-Only Match**: Node type with `_` signature (fallback)
3. **Fuzzy Search**: Substring matching on node types
4. **Confidence Scoring**: Prioritizes exact matches over fuzzy

## Performance

- **File Size**: ~1MB compressed for full registry (~125 signatures from 2 packages = ~0.01MB)
- **Load Time**: <100ms to load mappings
- **Resolution Time**: <10ms per node
- **Memory Usage**: ~10MB for full mappings
- **Build Time**: ~30s for 2 packages with pagination
- **Pagination**: Automatically handles multi-page node metadata (some packages have 5+ pages)

## Optimizations

- **Version Limiting**: Processes only recent versions per package (default: 5 most recent)
- **Automatic Pagination**: Fetches all pages of node metadata from registry
- **Rate Limiting**: Respectful API usage with delays between requests
- **Smart Caching**: Avoids re-processing unchanged versions
- **Incremental Updates**: Only processes new/changed versions when using `--input`

## Incremental Updates

The system supports incremental updates for daily/regular maintenance without reprocessing everything:

### How It Works

1. **Load Existing Data**: `--input` loads current mappings
2. **Version Comparison**: Compares registry versions with processed versions
3. **Process Only New**: Only fetches metadata for unprocessed versions
4. **Preserve Existing**: Keeps all existing mappings and adds new ones
5. **Track Changes**: Records statistics about what was added

### Example Workflow

```bash
# Initial full scan (one-time)
uv run scripts/build_global_mappings.py --limit 100 --output initial_mappings.json

# Daily incremental updates (fast)
uv run scripts/build_global_mappings.py --input initial_mappings.json --limit 100 --output updated_mappings.json

# Result: Only new package versions are processed, existing data preserved
```

### Performance Benefits

- **Fast Updates**: 1-2s when no changes, ~30s for typical daily updates
- **Bandwidth Efficient**: Only fetches new version metadata
- **Cumulative Building**: Each run adds to the total knowledge base
- **Safe**: Never loses existing mappings, only adds new ones

## Limitations

- Requires comfy-nodes metadata from registry (not all packages have this)
- Input signatures may not capture all semantic differences
- Version selection is simple (highest compatible version)
- No support for private/unreleased custom nodes
- Large packages with many versions are limited to recent versions for performance
- `--pages` mode is non-deterministic due to registry API ordering (use `--node-limit` for consistent results)

## Future Enhancements

- Machine learning for better confidence scoring
- Version compatibility matrices
- User feedback integration
- Support for GitHub-only packages
- Semantic similarity matching