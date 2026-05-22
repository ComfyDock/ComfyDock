# Running ComfyUI

Use `cg run` to launch ComfyUI from the selected ComfyGit environment.

```bash
cg run
```

Before launching, ComfyGit syncs the environment so the virtualenv, custom nodes,
model links, PyTorch backend, and local overlays match the manifest plus local
runtime configuration.

## Choose An Environment

Use the active environment:

```bash
cg use my-env
cg run
```

Or target one command:

```bash
cg -e my-env run
```

## Pass ComfyUI Arguments

ComfyGit owns flags before `--`. Arguments after `--` are passed to ComfyUI.

```bash
cg run -- --listen 0.0.0.0 --port 8188
```

Common examples:

```bash
cg run -- --port 8189
cg run -- --listen 0.0.0.0
cg run -- --auto-launch
```

## One-Time Runtime Overrides

Use a different PyTorch backend for one run:

```bash
cg run --torch-backend cpu
```

Apply an overlay for one run:

```bash
cg run --overlay local-dev
```

Install an optional extra for the run sync:

```bash
cg run --extra cuda
```

These operation-level flags do not rewrite the saved local environment config.

## Skip Sync

```bash
cg run --no-sync
```

Use `--no-sync` only when you deliberately want to bypass reconciliation. If the
runtime is stale, ComfyUI may start with missing packages, nodes, or model links.

## Open ComfyUI

By default, ComfyUI is available at:

```text
http://127.0.0.1:8188
```

If you bind to `0.0.0.0`, make sure the port is reachable from the browser or
machine that needs it.

!!! note "Media placeholder"
    Add a screenshot of a ComfyGit-managed ComfyUI window with the ComfyGit
    Manager panel visible.

## Run Vs Serve

`cg run` launches the full ComfyUI editor and backend.

`cg serve` fronts an already running ComfyUI backend with workflow contract
endpoints and the packaged Studio UI.

For Studio/API usage, run both:

```bash
cg run -- --port 8188
cg serve --port 8190 --comfy-url http://127.0.0.1:8188
```

Read more: [Serve workflows](../serve-studio/serving-workflows.md).
