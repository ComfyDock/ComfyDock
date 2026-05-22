# Workflows

A ComfyUI workflow is the editable graph JSON. ComfyGit can track workflows,
analyze node and model references, and store dependency metadata in the
environment manifest.

## Workflow Tracking

Tracked workflow files live under `workflows/`. ComfyGit treats them as portable
environment state, so they can be committed with the manifest and shared with
other users.

Workflow analysis can identify many custom node and model dependencies from the
graph. Some custom nodes load models through specialized logic that cannot be
inferred safely. For those cases, manually attach the indexed model to the
workflow.

## Workflow Contracts

A workflow contract is the public input/output shape for a workflow.

The supported authoring path is ComfyGit Manager inside ComfyUI. Manager can
inspect the loaded graph, let you choose public inputs and outputs, and capture
the same API-format prompt ComfyUI would submit for execution.

The editable workflow remains in `workflows/`. The executable API prompt
artifact for the saved contract lives in `workflow_api/`. Both are portable
tracked state when a workflow contract references them.

!!! note "Media placeholder"
    Add a diagram showing editable workflow JSON, contract metadata, and
    `workflow_api/*.api.json` as separate but connected artifacts.

Read more: [Workflow tracking](../user-guide/workflows/workflow-tracking.md),
[model dependencies](../user-guide/workflows/model-dependencies.md), and
[workflow contracts](../user-guide/workflows/workflow-contracts.md).
