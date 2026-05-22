# Workflow Commands

Workflow commands inspect saved ComfyUI workflows, resolve dependencies, and
manage workflow-level model declarations.

## List And Resolve

```bash
cg workflow list
cg workflow resolve WORKFLOW [--auto] [--install] [--no-install]
```

`resolve` analyzes workflow JSON, maps custom nodes to packages, matches model
references to the model index, and records dependency metadata in the manifest.

## Workflow Models

List models declared for a workflow:

```bash
cg workflow model list [WORKFLOW]
```

Declare an already-indexed local model as a workflow dependency:

```bash
cg workflow model add WORKFLOW --path RELATIVE_MODEL_PATH [--importance required|flexible|optional]
cg workflow model add WORKFLOW --hash HASH [--importance required|flexible|optional]
```

Remove a manually declared workflow model:

```bash
cg workflow model remove WORKFLOW --path RELATIVE_MODEL_PATH
cg workflow model remove WORKFLOW --hash HASH
```

Change model importance:

```bash
cg workflow model importance [WORKFLOW] [MODEL] [required|flexible|optional]
```

Use `importance` in user-facing docs. It maps to model criticality in the
manifest.

## Related Guides

- [Workflow resolution](../user-guide/workflows/workflow-resolution.md)
- [Workflow model dependencies](../user-guide/workflows/model-dependencies.md)
- [Workflow contracts](../user-guide/workflows/workflow-contracts.md)
