# Export And Import

Export and import are human handoff flows. Use them when someone wants to set up
an authoring environment from a portable environment recipe.

For Docker, CI, or runtime containers, use [materialize](materialize.md).

## Export

```bash
cg export my-env.tar.gz
```

Export includes portable environment files such as:

- `pyproject.toml`
- workflow JSON files
- workflow API prompt artifacts
- shared overlays
- package configuration
- model and node metadata

Export does not include:

- model bytes
- `.venv`
- local overlays
- cache databases
- logs
- local-only development checkout contents

If ComfyGit reports unresolved workflows or model source gaps, fix them before
export when possible. Use `--allow-issues` only for intentional work-in-progress
handoff:

```bash
cg export my-env.tar.gz --allow-issues
```

## Import

```bash
cg import my-env.tar.gz --name imported-env --use
```

Import from Git:

```bash
cg import https://github.com/team/my-env.git \
  --name team-env \
  --models required \
  --use
```

Choose model behavior:

```bash
cg import my-env.tar.gz --name imported-env --models all
cg import my-env.tar.gz --name imported-env --models required
cg import my-env.tar.gz --name imported-env --models skip
```

Skip Manager for a headless environment:

```bash
cg import my-env.tar.gz --name imported-env --no-manager
```

## After Import

```bash
cg use imported-env
cg status
cg run
```

If required models were skipped or could not be downloaded, resolve them before
claiming the workflow is reproducible.
