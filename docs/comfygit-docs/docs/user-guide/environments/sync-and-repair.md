# Sync And Repair

ComfyGit environments have a portable recipe and a local runtime. Sync and
repair are the commands that keep those two aligned.

## Sync

Use sync when you want the current runtime to match the manifest plus local
runtime configuration.

```bash
cg sync
```

Sync can:

- Resolve and install Python packages through uv.
- Apply the local PyTorch backend.
- Apply active overlays or one-time overlays.
- Install custom node dependency groups.
- Recreate the virtualenv when needed.
- Rebuild model links and runtime metadata.

Use `--verbose` when uv output matters:

```bash
cg sync --verbose
```

Use `--extra`, `--all-extras`, or `--overlay` for one operation:

```bash
cg sync --extra cuda
cg sync --overlay local-dev
```

## Run Syncs First

`cg run` syncs before launching ComfyUI unless you ask it not to:

```bash
cg run
cg run --no-sync
```

Use `--no-sync` only when you know the environment is already prepared and you
want to skip reconciliation for speed or debugging.

## Repair

Use repair when local runtime state has drifted or is damaged.

```bash
cg repair
```

Repair is useful after:

- Manual edits under `ComfyUI/custom_nodes`.
- Branch or checkout changes.
- A failed install.
- Deleted symlinks.
- Missing workflow copies.
- An interrupted environment setup.

Choose a model download strategy:

```bash
cg repair --models all
cg repair --models required
cg repair --models skip
```

## Git Operations Also Reconcile

Commands that move environment history, such as pull, checkout, reset, merge,
switch, and revert, may need to reconcile runtime state afterward.

```bash
cg pull -r origin --models required
cg switch experiment
cg revert <commit>
```

After a history change, check status:

```bash
cg status
```

## When To Use Which Command

Use `cg sync` when the manifest is right and the runtime needs to catch up.

Use `cg repair` when runtime state is suspicious, missing, or manually changed.

Use `cg materialize` when you are creating a fresh runtime from a portable source
in Docker, CI, or another machine.

## Related Guides

- [Local runtime config](local-runtime-config.md)
- [Materialize runtime environments](../collaboration/materialize.md)
- [Environment history](version-control.md)
