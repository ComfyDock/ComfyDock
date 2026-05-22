# Workflow Tracking

ComfyGit tracks ComfyUI workflow files as part of the environment recipe.

A tracked workflow can carry:

- the editable ComfyUI workflow JSON
- node package dependencies
- model dependencies
- source and criticality metadata
- workflow contract metadata
- captured API prompt artifacts for served contracts

## Where Workflows Live

ComfyUI saves workflow files in its user directory. ComfyGit copies tracked
workflow state into the environment repository so it can be committed and shared.

Use:

```bash
cg workflow list
```

to see tracked workflows and sync status.

## Add Or Update A Workflow

1. Open ComfyUI with `cg run`.
2. Create or load a workflow.
3. Save it from ComfyUI.
4. Use ComfyGit Manager or the CLI to resolve dependencies.

```bash
cg workflow resolve my-workflow
cg status
cg commit -m "Track my workflow"
```

## What Gets Committed

Workflow commits can include:

- `workflows/<name>.json`
- manifest workflow metadata
- model dependency entries
- custom node dependency references
- `workflow_api/<name>.api.json` when a workflow contract exists

Model bytes are not committed.

## When A Workflow Changes

After editing a workflow:

```bash
cg workflow resolve my-workflow
cg status
```

If the workflow has a saved contract and you changed mapped inputs, outputs, or
the graph behind them, re-save the contract in Manager.

Read more: [Workflow contracts](workflow-contracts.md).

!!! note "Media placeholder"
    Add a screenshot of Manager showing tracked workflows and sync status.
