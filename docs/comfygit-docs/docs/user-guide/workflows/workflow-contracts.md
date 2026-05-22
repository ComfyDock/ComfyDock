# Workflow Contracts

A workflow contract turns a ComfyUI workflow into a stable input/output shape.
It is the bridge between a graph on the canvas and a Studio/API surface that
other people or programs can use.

## Workflow JSON Vs Contract

A ComfyUI workflow JSON is the editable graph.

A ComfyGit workflow contract records:

- Which workflow it belongs to.
- Which fields are public inputs.
- Which output nodes become public outputs.
- Type information and validation metadata.
- A captured ComfyUI API-format prompt artifact.

The workflow stays editable. The contract is the public execution shape for a
saved version of that workflow.

## Author Contracts In Manager

The supported authoring path is ComfyGit Manager inside ComfyUI.

Manager can inspect the loaded graph and capture ComfyUI's native API prompt for
that exact workflow state. Core stores the contract in the manifest and writes
the captured API prompt under `workflow_api/`.


## What To Commit

When a contract is saved, the portable environment should include:

- `pyproject.toml`
- `workflows/<workflow>.json`
- `workflow_api/<workflow>.api.json`

If the manifest references a `workflow_api` artifact but the file is missing,
the contract is incomplete. Re-save the contract in Manager to repair it.

## When To Re-Save A Contract

Re-save the contract when you change:

- Public input bindings.
- Output bindings.
- The nodes or widgets behind a mapped input.
- Subgraph promoted widgets.
- The workflow shape in a way that affects execution.

Minor visual rearrangement of the graph may not require a new contract, but if
you are unsure, re-save and commit the result.

## Serve Existing Contracts

`cg serve` can run existing contracts from committed environment state. It does
not need Manager to author new contracts at runtime.

CLI-only environments can serve contracts that already exist, but Manager is the
supported path for creating new API-prompt-backed contracts.

## Related Guides

- [Serve workflows](../serve-studio/serving-workflows.md)
- [Uploads and file refs](../serve-studio/uploads.md)
- [Workflow tracking](workflow-tracking.md)
