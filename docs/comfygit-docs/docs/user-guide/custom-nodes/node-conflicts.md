# Node Conflicts

Node conflicts usually mean two things are trying to own the same runtime state:
a custom node directory, a Python dependency version, or a workflow node mapping.

Start by checking status:

```bash
cg status --verbose
```

## Existing Directory Conflicts

If a directory already exists under `custom_nodes/`, decide whether it should be
tracked, replaced, or left alone.

Track an existing local development directory:

```bash
cg node add my-node --dev
```

Replace a tracked node with a local checkout:

```bash
cg node dev-link my-node --path ~/dev/my-node --replace-existing
```

Untrack without deleting files:

```bash
cg node remove my-node --untrack
```

## Dependency Conflicts

Try a normal add first:

```bash
cg node add my-node
```

Use strict mode to fail instead of resolving:

```bash
cg node add my-node --strict
```

If the conflict is real, use constraints or overlays rather than manually
installing packages into `.venv`.

```bash
cg constraint add package<2
cg overlay create local-dev --local
cg overlay enable local-dev
```

## Workflow Mapping Conflicts

When ComfyGit cannot confidently map a workflow node type to one package, resolve
the workflow interactively:

```bash
cg workflow resolve my-workflow
```

Persisted workflow references should use canonical manifest package IDs.

## Repair Runtime Drift

After resolving conflicts:

```bash
cg repair
cg status
```

If a conflict came from a branch or pull, review the environment diff before
committing the repair.
