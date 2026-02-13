# Node Resolution Behavior

**Purpose**: Define how workflow node resolution should work across different scenarios.

**Scope**: Node resolution only (model resolution is separate). Applies to `workflow resolve` command.

## Resolution Priority Chain

When resolving a node type, check in order:

1. **Workflow-local custom_node_map** - User's explicit override for this workflow
2. **cnr_id from node properties** - Embedded metadata from ComfyUI
3. **Global mapping table** - Registry/manager data

User choice > embedded metadata > registry default.

## Pyproject.toml Structure

```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-a", "package-b"]  # Required dependencies
custom_node_map = {
  NodeTypeB = "package-b"      # User resolved ambiguous match
  NodeTypeC = false            # User marked optional
  NodeTypeD = "https://github.com/user/repo"  # Manual URL (not in registry)
}
```

**Key points**:
- `custom_node_map` is **per-workflow**, not global
- `nodes` = list of package IDs needed to run workflow
- `false` sentinel = optional node (no dependency needed)
- Manual GitHub URLs stored if not found in registry

## The 4-Step Resolution Flow

1. **Analyze workflow** - Extract all non-builtin nodes (no resolution, just read JSON)
2. **Resolve nodes** - Match against priority chain, categorize as resolved/ambiguous/unresolved
3. **Save resolutions** - Sync pyproject.toml to match resolution state (reconcile, not just append)
4. **Fix issues** - User resolves ambiguous/unresolved nodes interactively

## Case 1: Fresh Start (No Prior State)

**Step 1: Analyze**
```
Returns: [A, B, C]  # WorkflowNode objects
```

**Step 2: Resolve via global table**
```
A → package-a (exact match) → RESOLVED
B → [package-b (rank 1), package-g (rank 2)] → AMBIGUOUS
C → None → UNRESOLVED
```

**Step 3: Save to pyproject.toml**
```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-a"]  # Only auto-resolved nodes
```

**Step 4: Fix via user intervention**

Prompt 1 - Ambiguous node B:
```
Choice 1: package-b
Choice 2: package-g
[m] Manual ID/URL
[o] Mark optional
[s] Skip
```

User selects: `1` (package-b)

Actions (update pyproject.toml under this workflow):
- Add to `nodes = ["package-a", "package-b"]`
- Add to `custom_node_map`: `NodeTypeB = "package-b"`

Prompt 2 - Unresolved node C:
```
No matches found!
[m] Manual ID/URL
[o] Mark optional
[s] Skip
```

User selects: `o` (optional)

Actions:
- Add to `custom_node_map`: `NodeTypeC = false`
- Do NOT add to `nodes` (no dependency needed)

**Final state**:
```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-a", "package-b"]

[tool.comfygit.workflows.my_workflow.custom_node_map]
NodeTypeB = "package-b"
NodeTypeC = false
```

## Case 2: Incremental (Existing State + New Node)

**Existing pyproject.toml**:
```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-a", "package-b"]

[tool.comfygit.workflows.my_workflow.custom_node_map]
NodeTypeB = "package-b"
NodeTypeC = false
```

**Step 1: Analyze**
```
Returns: [A, B, C, D]  # New node D added!
```

**Step 2: Resolve (uses priority chain)**
```
A → Check custom_node_map: NOT PRESENT
  → Check cnr_id: NONE
  → Check global table: package-a → RESOLVED

B → Check custom_node_map: FOUND (package-b) → RESOLVED

C → Check custom_node_map: FOUND (false) → RESOLVED (optional)

D → Check custom_node_map: NOT PRESENT
  → Check cnr_id: FOUND (package-d) → RESOLVED
  → (Skip global table check)
```

**Step 3: Save (reconcile existing state)**

Compare resolutions against existing pyproject:
- A → package-a: Already in `nodes`, no change
- B → package-b: Already in `nodes` and `custom_node_map`, no change
- C → optional: Already in `custom_node_map`, no change
- D → package-d: NOT PRESENT, add to `nodes`

**Updated state**:
```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-a", "package-b", "package-d"]  # Added package-d

[tool.comfygit.workflows.my_workflow.custom_node_map]
NodeTypeB = "package-b"
NodeTypeC = false
```

**Step 4: Fix**
No unresolved issues, skip.

## Case 3: Node Removal (Cleanup Required)

**Existing pyproject.toml** (same as Case 2):
```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-a", "package-b", "package-d"]

[tool.comfygit.workflows.my_workflow.custom_node_map]
NodeTypeB = "package-b"
NodeTypeC = false
```

**Step 1: Analyze**
```
Returns: [D]  # User deleted A, B, C from workflow!
```

**Step 2: Resolve**
```
D → Check custom_node_map: NOT PRESENT
  → Check cnr_id: FOUND (package-d) → RESOLVED
```

Resolutions: `[D → package-d]`

**Step 3: Save (reconcile = cleanup orphans)**

Current resolutions: `[D → package-d]`
Existing pyproject:
- `nodes = [package-a, package-b, package-d]`
- `custom_node_map = {B → package-b, C → false}`

**Reconciliation logic**:
- Keep package-d (in current resolutions)
- DELETE package-a, package-b (not in current resolutions)
- DELETE custom_node_map entries for B, C (nodes not in workflow anymore)

**Final state**:
```toml
[tool.comfygit.workflows.my_workflow]
nodes = ["package-d"]

# custom_node_map section removed entirely (empty)
```

**Note**: Installed node packages are NOT uninstalled. Only workflow metadata cleaned up.

## Edge Case Handling

### Manual ID Validation

When user enters manual package ID:

1. **Validate**: Check if ID exists in global mapping packages table
2. **If not found**: Show error, re-prompt user
3. **If found**: Add to `nodes`, add to `custom_node_map`

```python
if manual_id not in global_mappings.packages:
    print(f"Error: '{manual_id}' not found in registry")
    # Re-prompt user
else:
    # Add to nodes and custom_node_map
```

### GitHub URL Normalization

When user enters GitHub URL:

1. **Normalize**: Convert to canonical form (`https://github.com/user/repo`)
2. **Search**: Check if URL exists in global mapping packages
3. **If found**:
   - Confirm with user: `"Found registry ID 'xyz' for this URL. Use it? [Y/n]"`
   - If yes: Use registry ID, add to `nodes`, add to `custom_node_map`
4. **If not found**:
   - Use raw URL, add to `nodes`, add to `custom_node_map`

```toml
# Found in registry
[tool.comfygit.workflows.my_workflow.custom_node_map]
NodeTypeX = "registry-package-id"

# Not found in registry
[tool.comfygit.workflows.my_workflow.custom_node_map]
NodeTypeX = "https://github.com/user/repo"
```

### Conflicting cnr_id Within Same Workflow

If multiple instances of same node type have different cnr_id values:

- **Current behavior**: Use first encountered (from deduplication logic)
- **Improvement**: Log warning so we can track if this happens in practice

```python
logger.warning(
    f"Conflicting cnr_id for {node_type}: "
    f"found both '{cnr_id_1}' and '{cnr_id_2}'. Using '{cnr_id_1}'."
)
```

### Invalid cnr_id from Properties

If node has `cnr_id` but it doesn't exist in global mappings:

- **Log warning** and continue (don't crash)
- Treat like manual ID: user might have private package

```python
if cnr_id not in global_mappings.packages:
    logger.warning(f"cnr_id '{cnr_id}' from properties not in registry")
    # Continue with fallback to global table lookup
```

### Empty custom_node_map After Cleanup

If cleanup removes all entries from `custom_node_map`:

- **Remove entire section** from pyproject.toml (don't keep empty dict)
- Absence = no custom mappings

### Skip Behavior

When user chooses "Skip":

- **Do NOT save** to pyproject.toml
- Node remains unresolved
- Will **re-prompt** on next `workflow resolve` run
- User can delete node or resolve it later

## Global Mapping Schema (New Format)

Updated schema supports ranked ambiguous matches:

```json
{
  "mappings": {
    "NodeTypeB::signature": [
      {
        "package_id": "package-b",
        "rank": 1,
        "source": "registry",
        "versions": ["1.0.0"]
      },
      {
        "package_id": "package-g",
        "rank": 2,
        "source": "manager",
        "versions": []
      }
    ]
  }
}
```

**Tie-breaking**: Preserve JSON order (first encountered wins). Future: add downloads/stars secondary sort.

## Important Notes

- **Reconciliation not additive**: `sync_resolution` (formerly `apply_resolution`) reconciles state to match current resolution, removing orphans. This should happen right after auto-resolution step in a batch, and ONLY then.
- **Progressive saving**: User choices written to pyproject after each choice in interactive resolution.
- **Workflow rename**: If user renames workflow file, state is lost. Re-resolve to create new section.
- **Package conflicts**: Multiple workflows can map same node type to different packages. This is allowed (user responsibility).
