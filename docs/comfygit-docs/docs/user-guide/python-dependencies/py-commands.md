# Python Dependencies

ComfyGit uses uv to resolve and sync Python packages for each environment.

Do not manually install packages into `.venv` and expect them to survive. Sync
can recreate the virtualenv. Capture durable dependencies with ComfyGit commands
or local overlays.

## Add Packages

```bash
cg py add requests
cg py add numpy==1.26.4
cg py add -r requirements.txt
```

Add to a dependency group:

```bash
cg py add package-name --group my-group
```

Add as editable when appropriate:

```bash
cg py add ~/dev/my-package --editable
```

## Remove Packages

```bash
cg py remove requests
cg py remove package-name --group my-group
cg py remove-group my-group
```

## List Dependencies

```bash
cg py list
cg py list --all
```

## Custom Node Dependencies

Custom node dependencies are tracked in dependency groups. ComfyGit generates
group names that avoid collisions between nodes.

Use `cg node add`, `cg node update`, and `cg node remove` so node dependency
metadata stays consistent with installed node metadata.

## Optional Extras

Install an extra for one sync or run:

```bash
cg sync --extra cuda
cg run --extra cuda
```

Save default extras for this environment on this machine:

```bash
cg env-config extras add cuda
cg env-config extras show
```

## Local Sources And Overlays

Use overlays for machine-local source paths, package indexes, or temporary
dependency changes:

```bash
cg overlay create local-dev --local
cg overlay enable local-dev
cg sync --overlay local-dev
```

Read more: [Local runtime config](../environments/local-runtime-config.md).

## UV Passthrough

Advanced users can run uv through ComfyGit:

```bash
cg py uv pip list
```

Prefer ComfyGit commands for changes that should stay represented in the
environment manifest.
