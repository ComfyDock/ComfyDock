# Workflow Contract Reference

A workflow contract is the saved public input/output shape for a workflow.

Contracts let ComfyGit turn a ComfyUI workflow into a stable Studio/API surface
without exposing the full internal graph as the public interface.

## Stored Contract State

A contract is represented by:

- the tracked editable workflow under `workflows/`
- contract metadata in the environment manifest
- a captured ComfyUI API prompt artifact under `workflow_api/`

The API prompt artifact is important. Runtime callers should execute the
captured prompt and patch declared public inputs into it. They should not try to
regenerate a ComfyUI API prompt from the editable workflow at serve time.

## Contract Inputs

Inputs describe the public fields a caller can provide. They map back to
specific ComfyUI node inputs in the captured API prompt.

Typical input metadata includes:

- public input name
- input type
- target node and input path
- default value, when available
- UI metadata, when available

## Contract Outputs

Outputs describe the artifacts or values a caller expects back after execution.
They map to ComfyUI output nodes or output data discovered from execution
history.

`cg serve` normalizes those outputs into the contract response shape.

## Authoring And Execution

Use Manager to author or update contracts. Use `cg serve` to execute saved
contracts from environment state.

```bash
cg run
cg serve --port 8190 --comfy-url http://127.0.0.1:8188
```

## Related Pages

- [Workflow contracts guide](../user-guide/workflows/workflow-contracts.md)
- [Studio and serve concept](../concepts/studio-and-serve.md)
- [Serve API reference](serve-api.md)
