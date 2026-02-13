# ComfyGit Model Tracking and Download System

## Overview

ComfyGit tracks models through a two-layer system:
1. **pyproject.toml** - Configuration and manifest layer (committed to git)
2. **SQLite Database** - Fast indexed access and source tracking (runtime state)

This document explains how models flow through the system from tracking to download.

---

## Part 1: Model Storage in pyproject.toml

### 1.1 Global Models Table

All models that have been resolved are stored in `[tool.comfygit.models]`:

```toml
[tool.comfygit.models]
"abc1234567890abc" = { filename = "my_model.safetensors", size = 5368709120, relative_path = "checkpoints/my_model.safetensors", category = "checkpoints", sources = ["https://civitai.com/..."] }
```

**Structure (ManifestModel):**
- `hash` (key) - Short blake3 hash for deduplication
- `filename` - Original filename
- `size` - File size in bytes
- `relative_path` - Expected location in models directory
- `category` - Type (checkpoints, loras, vae, etc.)
- `sources` - List of URLs where model can be downloaded

**Purpose:** Deduplication and global reference for workflows.

### 1.2 Per-Workflow Models

Each workflow stores its own model list in `[tool.comfygit.workflows.<name>.models]`:

```toml
[tool.comfygit.workflows.my_workflow]
models = [
  { filename = "my_model.safetensors", category = "checkpoints", criticality = "required", status = "resolved", hash = "abc1234567890abc", nodes = [{ node_id = "123", node_type = "LoadImage", widget_idx = 0, widget_value = "my_model.safetensors" }] },
  { filename = "lora.safetensors", category = "loras", criticality = "optional", status = "unresolved", sources = ["https://..."], relative_path = "loras/lora.safetensors", nodes = [...] }
]
```

**ManifestWorkflowModel structure:**
- `filename` - Model filename
- `category` - Model type
- `criticality` - "required" or "optional"
- `status` - "resolved" (hash set) or "unresolved" (no hash, has sources)
- `hash` - Blake3 hash IF resolved (links to global table)
- `sources` - List of URLs IF unresolved
- `relative_path` - Target path IF unresolved
- `nodes` - List of nodes that use this model with specific widget references

**Two States:**

1. **Resolved** (`status: "resolved"`, `hash` set):
   - Model exists locally and has been verified
   - Hash links to `[tool.comfygit.models]` global table
   - No `sources` field needed (can be looked up in global table)

2. **Unresolved** (`status: "unresolved"`, `hash` is null):
   - Model not found locally OR could not download
   - Has `sources` (URLs to download from)
   - Has `relative_path` (where to save after download)
   - Will be resolved when model downloads completes

---

## Part 2: SQLite Model Index

The SQLite database at `<workspace>/comfygit_cache/models.db` tracks runtime state:

### 2.1 Models Table
Primary key: `hash` (short hash)

```sql
CREATE TABLE models (
  hash TEXT PRIMARY KEY,           -- Short blake3 hash
  file_size INTEGER,              -- File size in bytes
  blake3_hash TEXT,               -- Full blake3 (for collisions)
  sha256_hash TEXT,               -- SHA256 for compatibility
  first_seen INTEGER,             -- Timestamp
  metadata TEXT                   -- JSON metadata
)
```

### 2.2 Model Locations Table
Links models to actual files on disk:

```sql
CREATE TABLE model_locations (
  id INTEGER PRIMARY KEY,
  model_hash TEXT,                -- Foreign key to models.hash
  base_directory TEXT,            -- e.g., /workspace/models
  relative_path TEXT,             -- e.g., checkpoints/model.safetensors
  filename TEXT,                  -- Just the filename
  mtime REAL,                     -- File modification time
  last_seen INTEGER               -- Timestamp
)
```

**Key points:**
- One model (hash) can have multiple locations
- Each location is tied to a specific `base_directory`
- Supports switching model directories without re-hashing

### 2.3 Model Sources Table
Tracks where models can be downloaded from:

```sql
CREATE TABLE model_sources (
  id INTEGER PRIMARY KEY,
  model_hash TEXT,                -- Foreign key to models.hash
  source_type TEXT,               -- 'civitai', 'huggingface', 'custom', 'url'
  source_url TEXT,                -- Full download URL
  metadata TEXT,                  -- JSON with extra metadata
  added_time INTEGER              -- Timestamp
)
```

**Populated by:**
- Download intents being resolved (when you download)
- Manual source additions via `add_model_source()`
- Import process enrichment from pyproject.toml

---

## Part 3: Model Tracking Flow

### 3.1 Adding Models to Environment (After Download)

When a model is downloaded:

```
URL Download
    ↓
1. Download file to temp location
2. Calculate short hash + full blake3 during streaming
3. Move to target path
4. Update SQLite:
   - models.ensure_model(hash, file_size, blake3_hash)
   - model_locations.add_location(hash, base_dir, relative_path, ...)
   - model_sources.add_source(hash, source_type, url)
5. Update pyproject.toml:
   - Add to [tool.comfygit.models.<hash>]
   - Update workflow model reference with hash
```

**Code path:** `ModelDownloader.download()` → `ModelRepository.ensure_model()`, `.add_location()`, `.add_source()`

### 3.2 Detecting Missing Models

When resolving workflows for import or repair:

```
prepare_import_with_model_strategy()
    ↓
For each workflow model:
    1. Check if model.hash exists in SQLite
       existing = repository.get_model(model.hash)
    2. If found locally:
       - Leave status="resolved"
       - Enrich SQLite sources from pyproject.toml sources
    3. If NOT found locally:
       - Check model_strategy ("all", "required", "skip")
       - If "all" or model is "required":
         * Convert to download intent
         * Set status="unresolved"
         * Clear hash (will be set after download)
         * Keep sources and relative_path
       - If "skip":
         * Leave as optional unresolved
         * No download will be attempted
```

**Code:** `Environment.prepare_import_with_model_strategy()` lines 931-1030

### 3.3 Creating Download Intents

A "download intent" is a workflow model that needs downloading:

**Structure (ManifestWorkflowModel):**
```python
{
    "filename": "model.safetensors",
    "category": "checkpoints",
    "criticality": "required",
    "status": "unresolved",        # NOT resolved yet
    "sources": ["https://..."],    # Where to get it
    "relative_path": "checkpoints/model.safetensors",
    "hash": null,                  # Will be set after download
    "nodes": [...]                 # Which nodes use it
}
```

**Created by:** `prepare_import_with_model_strategy()` when:
1. Model hash not found in SQLite
2. Model strategy allows downloads
3. Model has sources in pyproject

### 3.4 Executing Downloads

When `resolve_workflow()` is called with download intents:

```
_execute_pending_downloads(result, callbacks)
    ↓
For each download intent in result.models_resolved:
    1. Check deduplication:
       existing = repository.find_by_source_url(url)
       if exists: reuse existing model
    
    2. Create download request:
       DownloadRequest(url, target_path, workflow_name)
    
    3. Download via ModelDownloader:
       download_result = model_downloader.download(request)
    
    4. Update pyproject with actual hash:
       workflow_manager._update_model_hash(workflow, node_ref, hash)
    
    5. Execute callbacks for CLI progress
```

**Code:** `Environment._execute_pending_downloads()` lines 741-837

---

## Part 4: Model Index Repository

The `ModelRepository` class is the central access point for SQLite:

### 4.1 Checking Model Existence

```python
# Simple existence check
exists = repository.has_model(hash)

# Get model with all details
model = repository.get_model(hash)  # Returns ModelWithLocation

# Search by various criteria
models = repository.find_model_by_hash(query)
models = repository.find_by_filename(filename)
models = repository.find_by_exact_path(relative_path)
models = repository.search(term)
```

### 4.2 Model Scanning

Before resolving workflows, scan models directory:

```
workspace.sync_model_directory()
    ↓
ModelScanner.scan_directory(models_path)
    ↓
For each file in models_path:
    1. Calculate short hash
    2. Check if hash exists in index
    3. If new: add to models + model_locations tables
    4. If existing: update location + mtime
    5. Clean stale locations (files that no longer exist)
```

**Code:** `ModelScanner.scan_directory()` in `analyzers/model_scanner.py`

### 4.3 Source Tracking

Sources are accumulated from multiple places:

```python
# Add a source to an existing model
repository.add_source(
    model_hash="abc123",
    source_type="civitai",
    source_url="https://civitai.com/...",
    metadata={"model_id": "123"}
)

# Get all sources for a model
sources = repository.get_sources(model_hash)
# Returns: [{"type": "civitai", "url": "...", "metadata": {...}}]

# Find model by source URL
model = repository.find_by_source_url(url)
```

---

## Part 5: Complete Import Flow with Models

### 5.1 Import from Tarball

```
workspace.import_environment(tarball, name, model_strategy)
    ↓
1. EnvironmentFactory.import_from_bundle():
   - Extract .tar.gz to environment/.cec/
   - Create pyproject.toml with [tool.comfygit.models] and [tool.comfygit.workflows]
    
2. environment.finalize_import(model_strategy):
   
   Phase 1-5: Setup ComfyUI, dependencies, git, workflows, nodes
   
   Phase 6: Prepare and resolve models
       ↓
       prepare_import_with_model_strategy(model_strategy)
           ↓
           For each workflow:
               For each model in workflow:
                   if model.hash exists in SQLite:
                       → Keep resolved
                       → Enrich SQLite sources
                   else:
                       → Convert to download intent
       
       resolve_workflow() for each workflow with intents
           ↓
           Workflow dependency analysis
           Model resolution against available models
           _execute_pending_downloads()
               ↓
               For each download intent:
                   1. Check if URL already downloaded (dedup)
                   2. Create DownloadRequest
                   3. ModelDownloader.download():
                      - Stream download from URL
                      - Calculate hashes during download
                      - Move to target path
                      - Update SQLite models, locations, sources
                   4. Update pyproject with actual hash
                   5. Callback to CLI for progress
```

### 5.2 Model Strategy Options

- **"all"** - Download all models with sources (default for import)
- **"required"** - Only download models marked as criticality="required"
- **"skip"** - Don't download, leave as optional unresolved

---

## Part 6: What Already Exists for Repair

The repair command can reuse:

### 6.1 Missing Model Detection
```python
# Analyze which models are missing
for model in pyproject.workflows.get_workflow_models(workflow):
    existing = model_repository.get_model(model.hash)
    if not existing:
        # This model is missing locally
        # Can create download intent
```

### 6.2 Download Intent Creation
```python
# Already implemented in prepare_import_with_model_strategy()
# Converts resolved models to download intents when missing
models[idx].status = "unresolved"
models[idx].sources = global_model.sources
models[idx].relative_path = global_model.relative_path
models[idx].hash = None
```

### 6.3 Download Execution
```python
# Already implemented in _execute_pending_downloads()
# Handles batch downloads with deduplication and progress
for resolved in result.models_resolved:
    if resolved.match_type == "download_intent":
        download_result = model_downloader.download(request)
        # Update pyproject with hash
        workflow_manager._update_model_hash(workflow, ref, hash)
```

### 6.4 Source Enrichment
```python
# After downloading, sources can be enriched
# From CivitAI/HuggingFace lookups or user additions
model_repository.add_source(
    model_hash=hash,
    source_type="civitai",
    source_url=url
)
```

### 6.5 Model Scanning
```python
# Sync model directory to find any manually added models
workspace.sync_model_directory(progress_callback)
# Automatically indexes new models
```

---

## Part 7: Data Structure Summary

### ManifestModel (Stored in [tool.comfygit.models])
```python
@dataclass
class ManifestModel:
    hash: str              # Primary key
    filename: str
    size: int
    relative_path: str
    category: str
    sources: list[str] = field(default_factory=list)
```

### ManifestWorkflowModel (Stored in [tool.comfygit.workflows.<name>.models])
```python
@dataclass
class ManifestWorkflowModel:
    filename: str
    category: str
    criticality: str       # "required" or "optional"
    status: str            # "resolved" or "unresolved"
    nodes: list[WorkflowNodeWidgetRef]
    hash: str | None = None             # Set if resolved
    sources: list[str] = field(default_factory=list)  # If unresolved
    relative_path: str | None = None    # If unresolved
```

### ModelWithLocation (From SQLite)
```python
@dataclass
class ModelWithLocation:
    hash: str
    file_size: int
    blake3_hash: str
    sha256_hash: str | None
    relative_path: str
    filename: str
    mtime: float
    last_seen: int
    base_directory: str | None = None
    metadata: dict = field(default_factory=dict)
```

---

## Part 8: Key Integration Points

For implementing repair with model downloads:

1. **Detect missing** - Use `ModelRepository.get_model(hash)` to check
2. **Create intents** - Use existing logic in `prepare_import_with_model_strategy()`
3. **Download** - Use existing `_execute_pending_downloads()` logic
4. **Update config** - Use `workflow_manager._update_model_hash()` to write resolved hash
5. **Progress** - Use `BatchDownloadCallbacks` for CLI feedback
6. **Index models** - Already handles in download flow

The machinery for model download exists and is used by import. Repair just needs to:
1. Detect which models are missing (check SQLite)
2. Find their sources (from pyproject.toml global table)
3. Create download intents (convert to unresolved temporarily)
4. Call resolve_workflow() (handles downloads)
5. Report results to user

