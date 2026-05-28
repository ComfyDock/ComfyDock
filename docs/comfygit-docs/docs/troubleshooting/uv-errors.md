# UV Errors

ComfyGit uses uv for Python dependency resolution and sync. When uv fails, the
environment usually needs clearer dependency metadata, a constraint, or a local
runtime configuration change.

## Show Full Output

```bash
cg sync --verbose
```

## Check PyTorch Backend

```bash
cg env-config torch-backend show
cg env-config torch-backend detect
cg env-config torch-backend set cu128
```

Use concrete backend names such as `cpu`, `cu128`, `cu126`, `cu124`, `rocm6.3`,
or `xpu`.

## Add Constraints

```bash
cg constraint add "package<2"
cg sync
```

## Use Overlays For Local Sources

```bash
cg overlay create local-dev --local
cg overlay enable local-dev
cg sync --overlay local-dev
```

## Repair Tooling

```bash
cg doctor --check-only
cg doctor
```

If uv itself inside the environment is broken, `doctor` can inspect and repair
environment tooling.
