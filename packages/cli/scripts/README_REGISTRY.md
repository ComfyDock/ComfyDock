# Registry Cache and Mappings Scripts

## Overview

Progressive enhancement process for building node mappings efficiently:
1. **build_registry_cache.py** - Three-phase progressive fetching of registry data
2. **build_global_mappings.py** - Works entirely offline from cache to build mappings

## Usage

### Step 1: Build Registry Cache (Progressive Enhancement)

#### Phase 1: Basic Node Information
```bash
# Fetch only basic node info (fast, ~3000 nodes)
uv run scripts/build_registry_cache.py \
  --output cache.json \
  --no-versions --no-metadata \
  --nodes-per-page 100
```

#### Phase 2: Add Versions & Install Data
```bash
# Add versions and download URLs to existing cache
uv run scripts/build_registry_cache.py \
  --input cache.json --output cache.json \
  --no-nodes --no-metadata \
  --checkpoint-interval 20
```

#### Phase 3: Add Metadata (Selective)
```bash
# Add metadata for latest 10 versions per node
uv run scripts/build_registry_cache.py \
  --input cache.json --output cache.json \
  --no-nodes --no-versions \
  --max-versions 10
```

#### Or Build Everything at Once
```bash
# Traditional approach - all phases in one run
uv run scripts/build_registry_cache.py \
  --output src/comfygit_core/data/registry_cache.json \
  --concurrency 10 \
  --max-versions 10
```

### Step 2: Build Node Mappings

```bash
# Build mappings from cache
uv run scripts/build_global_mappings.py \
  --cache src/comfygit_core/data/registry_cache.json \
  --output src/comfygit_core/data/node_mappings.json \
  --concurrency 10 \
  --checkpoint-interval 20

# Incremental update (only process new versions)
uv run scripts/build_global_mappings.py \
  --cache src/comfygit_core/data/registry_cache.json \
  --input src/comfygit_core/data/node_mappings.json \
  --output src/comfygit_core/data/node_mappings.json \
  --max-versions 10
```

## Benefits

- **Complete offline processing**: Cache contains ALL data - no API calls needed for mappings
- **Fast iteration on mapping logic**: Change mapping table design without hitting API
- **Incremental cache updates**: Skip already-cached versions when refreshing
- **Checkpoint support**: Both scripts save progress regularly
- **Metadata included**: All comfy-nodes metadata is cached for each version

## Cache Structure

```json
{
  "cached_at": "2025-09-19T12:45:30.088055",
  "node_count": 2913,
  "versions_processed": 15000,
  "metadata_entries": 150000,
  "nodes": [
    {
      "id": "node-id",
      "name": "Node Name",
      "fully_cached": true,
      "versions_list": [
        {
          "version": "1.0.0",
          "download_url": "...",
          "dependencies": [...],
          "comfy_nodes": [
            {
              "comfy_node_name": "NodeName",
              "input_types": {...},
              "return_types": [...]
            }
          ],
          "metadata_cached": true
        }
      ],
      "versions_cached_at": "..."
    }
  ]
}
```

## Options

### build_registry_cache.py
- `--output`: Cache file path
- `--input`: Existing cache for incremental update
- `--no-nodes`: Skip Phase 1 (basic node fetching)
- `--no-versions`: Skip Phase 2 (versions & install data)
- `--no-metadata`: Skip Phase 3 (comfy-nodes metadata)
- `--nodes-per-page`: Nodes per API page (default: 100)
- `--max-versions`: Max versions for metadata (-1 for all, default: -1)
- `--concurrency`: Parallel requests (default: 10)
- `--checkpoint-interval`: Save every N nodes (default: 20)
- `--pages`: Limit pages fetched in Phase 1 (for testing)
- `--log-level`: DEBUG, INFO, WARNING, ERROR

### build_global_mappings.py
- `--cache`: Registry cache file (required)
- `--input`: Existing mappings for incremental update
- `--output`: Output mappings file
- `--max-versions`: Limit versions per package (-1 for all)
- `--checkpoint-interval`: Save every N packages (default: 50)
- `--log-level`: DEBUG, INFO, WARNING, ERROR