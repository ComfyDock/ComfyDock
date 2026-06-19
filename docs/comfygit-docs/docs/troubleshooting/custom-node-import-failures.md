# Custom Node Import Failures

Custom node failures can come from several layers:

- the node is not tracked in the manifest
- the node is tracked but not installed in `custom_nodes/`
- Python dependencies are not synced
- uv cannot resolve the node's dependencies
- ComfyUI starts, but the node fails to import at runtime

Start by finding which layer is failing before changing packages.

## Check Environment Status

```bash
cg status --verbose
```

Look for:

- missing or extra custom nodes
- packages out of sync
- runtime import failures
- workflows with unresolved nodes or models

If the environment is simply out of sync, run:

```bash
cg sync --verbose
cg run
```

If you use a local overlay or a specific PyTorch backend, include those inputs:

```bash
cg sync --overlay .local --torch-backend cu126 --verbose
```

## Inspect Logs

For CLI-managed runs:

```bash
cg debug -n 200 --level ERROR
```

For orchestrator-managed ComfyUI processes:

```bash
cg orch logs -n 200
```

The ComfyUI traceback is usually the most important signal. Common examples:

| Error | Usually Means |
| --- | --- |
| `ModuleNotFoundError: No module named 'soundfile'` | A Python dependency is missing. |
| `ImportError: cannot import name ... from ...` | A package version mismatch. |
| `No solution found when resolving dependencies` | uv cannot solve the requested package set. |
| `fatal error: portaudio.h: No such file` | A native build needs an OS library/header. |
| `command 'gcc' failed` | A dependency needs a compiler or native library. |

## Re-run The Node Install Verbosely

If the failure happened while adding a node:

```bash
cg node add NODE --verbose
```

Use strict mode when you want uv conflicts to fail instead of being
auto-adjusted:

```bash
cg node add NODE --strict --verbose
```

Use overlays during install preflight when the environment depends on active
local or shared overlays:

```bash
cg node add NODE --resolve-with-overlays --verbose
```

If the dependency probe fails but you understand the failure and still want to
try the project-level solve, you can bypass the probe:

```bash
cg node add NODE --resolve-with-overlays --no-test --verbose
cg sync --overlay .local --verbose
```

Use `--no-test` carefully. It skips ComfyGit's preflight dependency check; uv
sync can still fail afterward.

## Choose The Right Fix

### Add A Portable Constraint

Use a constraint when the version policy should travel with the environment:

```bash
cg constraint add "package<2"
cg sync --verbose
```

This is appropriate when the environment requires that range on every machine.

### Add A Local Overlay Constraint

Use a local overlay when the fix is machine-specific, CUDA-specific,
Python-version-specific, or still experimental:

```bash
cg overlay create --local
```

Then edit `.cec/overlays/.local.toml` and add constraints:

```toml
[constraints]
packages = [
  "package<2",
]
```

Run sync with the overlay:

```bash
cg sync --overlay .local --verbose
```

Local overlays are useful for testing fixes without changing the portable
manifest.

### Add A Missing Python Dependency

If the traceback clearly shows a missing Python package and that package should
be part of the portable environment:

```bash
cg py add package-name
cg sync --verbose
```

If the package is only needed on one machine, prefer a local overlay instead.

### Install A Missing System Library

Some Python packages compile native extensions. If the error mentions a missing
header such as `portaudio.h`, the fix may be an OS package rather than a
ComfyGit manifest change.

Examples:

- Ubuntu/Debian: install the relevant `*-dev` package
- Windows: install the required build tools or choose a package version with a
  compatible wheel
- macOS: install the relevant library with Homebrew

After changing system packages, run:

```bash
cg sync --verbose
cg run
```

## Example: Dependency Chain Pulls A Bad Version

A node may fail because one dependency pulls a newer transitive dependency that
does not work on your platform.

For example, a node might depend on package `A`, package `A` depends on package
`B`, and the newest package `B` requires a native system library that your
machine does not have.

In that case, a local overlay constraint is often safer than random manual
installs:

```toml
[constraints]
packages = [
  "B==1.2.3",
]
```

Then:

```bash
cg sync --overlay .local --verbose
```

If the constraint should be shared by everyone using the environment, promote it
to the tracked manifest with `cg constraint add`.

## Avoid Manual Venv Fixes

Avoid using bare `pip install` or `uv pip install` inside `.venv` as the final
fix. It can be useful for a temporary experiment, but ComfyGit may recreate or
resync the virtual environment later.

Durable fixes should be captured as one of:

- tracked node metadata
- `cg py add ...`
- `cg constraint add ...`
- local or shared overlays
- an OS-level prerequisite documented for the environment

## What To Include In A Bug Report

Include:

- OS and Python version
- ComfyGit CLI version and Manager version
- node pack name and version/ref
- whether the node came from the Registry, Git, or a local checkout
- `cg status --verbose`
- the ComfyUI import traceback
- whether you used overlays or a PyTorch backend override

This information usually shows whether the problem is manifest state, uv
resolution, a local runtime dependency, or a third-party node bug.
