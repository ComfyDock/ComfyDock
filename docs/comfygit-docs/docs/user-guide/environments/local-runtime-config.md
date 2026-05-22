# Local Runtime Config

Some environment settings should follow the current machine, not the shared
environment commit.

ComfyGit keeps those settings local and injects them during sync or run. This
lets two users share the same environment while using different hardware,
different local package checkouts, or different temporary dependency overrides.

## PyTorch Backend

The PyTorch backend controls which torch packages are installed for the current
machine.

```bash
cg env-config torch-backend detect
cg env-config torch-backend set cu128
cg env-config torch-backend show
```

Useful backend values include:

- `auto` - detect the best option.
- `cpu` - install CPU-only torch.
- `cu128`, `cu126`, `cu124` - NVIDIA CUDA builds.
- `rocm6.3` - AMD ROCm.
- `xpu` - Intel XPU.

One-time overrides are available on operations that sync:

```bash
cg sync --torch-backend cpu
cg run --torch-backend cu128
cg pull --torch-backend auto
```

A one-time override does not rewrite your saved local backend preference.

## Optional Sync Extras

Some dependencies are optional. You can install an extra for one sync:

```bash
cg sync --extra cuda
```

Or save default extras for this environment on this machine:

```bash
cg env-config extras add cuda
cg env-config extras show
cg env-config extras remove cuda
```

## Dependency Overlays

Overlays are dependency configuration snippets that ComfyGit can apply during
sync without making every local experiment part of the main manifest.

Create a local overlay:

```bash
cg overlay create local-dev --local
cg overlay enable local-dev
cg overlay list --active
```

Use an overlay for one operation:

```bash
cg sync --overlay local-dev
cg run --overlay local-dev
cg node add my-node --resolve-with-overlays
```

Use local overlays for machine-specific package indexes, editable package paths,
or temporary dependency changes. Use shared overlays only when the whole team
should have the same optional dependency layer.


## What Not To Do

Do not manually install packages into `.venv` and expect them to survive. `cg
sync` may recreate the virtualenv.

Instead:

- Use `cg py add` for portable project dependencies.
- Use `cg env-config extras` for local default extras.
- Use overlays for local source/index/package overrides.
- Use `cg node add` so custom node dependencies are tracked.

## Related Guides

- [Sync and repair](sync-and-repair.md)
- [Python dependencies](../python-dependencies/py-commands.md)
- [Constraints](../python-dependencies/constraints.md)
