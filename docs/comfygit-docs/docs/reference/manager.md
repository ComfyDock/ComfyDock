# Manager Reference

ComfyGit Manager is the ComfyUI custom node and panel that lets users manage a
ComfyGit environment from inside ComfyUI.

The Manager UI is the supported browser-facing surface for actions that need the
live ComfyUI graph or a user-friendly control panel.

## Manager Owns

- environment status display
- workflow tracking actions
- workflow contract authoring
- workflow input/output mapping
- manual workflow model dependency selection
- model source entry and model download queue UI
- custom node install/update/remove UI
- environment switch and restart coordination

## Manager Does Not Own

Manager does not replace the core library or the CLI. It calls into ComfyGit
core behavior and environment orchestration rather than inventing separate
manifest semantics.

Manager also should not be the only way to consume saved workflow contracts.
Once a contract is saved, `cg serve` and other runtime adapters can execute it
from committed environment state.

## Versioning

Manager is installed as a ComfyUI custom node in each environment. Keep it
updated when the manifest features used by the environment require a newer
manager:

```bash
cg manager status
cg manager update
```

Restart the environment after updating Manager.

## Related Pages

- [Workflow contracts](workflow-contracts.md)
- [Workflow model dependencies](../user-guide/workflows/model-dependencies.md)
- [Adding custom nodes](../user-guide/custom-nodes/adding-nodes.md)
