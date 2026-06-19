# Common Issues

Start with the status and logs:

```bash
cg status --verbose
cg debug -n 100
```

For orchestrator-managed ComfyUI processes:

```bash
cg orch status
cg orch logs -n 100
```

## ComfyUI Does Not Start

Try a sync first:

```bash
cg sync --verbose
```

Then run:

```bash
cg run
```

If runtime files were edited manually:

```bash
cg repair
```

## A Custom Node Is Missing

Check installed nodes:

```bash
cg node list
```

Resolve the workflow:

```bash
cg workflow resolve my-workflow
```

If the node directory exists but is not tracked, either track it as development
or remove/untrack it intentionally.

If the node is installed but fails to import after restart, see
[Custom node import failures](custom-node-import-failures.md).

## A Model Is Missing

Rescan the index:

```bash
cg model index sync
cg model index find model-name
```

If the workflow needs a model ComfyGit did not detect:

```bash
cg workflow model add my-workflow --path path/under/models.safetensors
```

## Dependency Sync Fails

Use verbose sync:

```bash
cg sync --verbose
```

Then decide whether the fix is a node update, a constraint, an overlay, or a
separate environment.

## Manager Update Fails

Check Manager status:

```bash
cg manager status
cg manager update --yes
```

If self-update cannot complete from the running Manager panel, use the ComfyGit
panel's manual update instructions or run the CLI command from the environment
context, then restart ComfyUI.

## When In Doubt

Use repair before deleting files manually:

```bash
cg repair
cg status
```

If repair reports unresolved source/model/node issues, fix those explicitly
instead of mutating `.venv` or `custom_nodes/` by hand.
