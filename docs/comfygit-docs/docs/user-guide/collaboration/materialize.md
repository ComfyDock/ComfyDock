# Materialize Runtime Environments

`cg materialize` hydrates a portable ComfyGit environment into a local runtime.
It is built for Dockerfiles, CI jobs, remote machines, and API-serving
containers.

Materialize is related to import, but it is not the same flow.

- **Import** is for a person setting up an authoring environment.
- **Materialize** is for scripts and runtimes that need a declared environment
  without prompts.

## Basic Usage

```bash
cg materialize https://github.com/team/my-env.git \
  --name my-runtime \
  --models required \
  --torch-backend auto \
  --replace
```

Sources can be:

- A Git repository URL.
- An exported `.tar.gz` bundle.
- A local directory containing a portable environment manifest.

## Runtime-Safe Defaults

Materialize defaults are conservative:

- Models are skipped unless you choose `--models required` or `--models all`.
- ComfyGit Manager is not installed unless you pass `--with-manager`.
- Sync failures fail the command.
- No authoring import commit is created.
- PyTorch backend defaults to `auto`.

That makes materialization suitable for build and runtime contexts.

## Common Options

```bash
cg materialize SOURCE --name runtime-env
cg materialize SOURCE --name runtime-env --workspace /opt/comfygit
cg materialize SOURCE --name runtime-env --models-dir /models
cg materialize SOURCE --name runtime-env --branch main
cg materialize SOURCE --name runtime-env --models required
cg materialize SOURCE --name runtime-env --with-manager
cg materialize SOURCE --name runtime-env --replace
```

Use `--with-manager` only when the runtime needs the Manager custom node. A
served runtime can run existing workflow contracts after authoring without using
Manager as the authoring UI.

## Directory Sources

When you materialize from a plain directory, ComfyGit copies portable recipe
files, not runtime state.

It can copy files such as:

- `pyproject.toml`
- `.python-version`
- `package_config.toml`
- `workflows/`
- `workflow_api/`
- shared overlays

It does not copy:

- `.git/`
- `.venv/`
- local overlays
- ComfyUI runtime checkouts
- generated databases
- logs
- model bytes

## What Materialize Does Not Do

Materialize prepares an environment. It does not launch ComfyUI, start
`cg serve`, bind network ports, or expose an endpoint.

Typical runtime entrypoints look like:

```bash
cg materialize "$ENV_REPO" --name runtime --models required --replace
cg -e runtime run -- --listen 0.0.0.0 --port 8188
```

or, for a served contract runtime:

```bash
cg -e runtime run -- --listen 127.0.0.1 --port 8188
cg -e runtime serve --host 0.0.0.0 --port 8190 --comfy-url http://127.0.0.1:8188
```

!!! note "Media placeholder"
    Add a diagram showing Git/bundle/directory sources feeding
    `cg materialize`, then `cg run` and `cg serve` as separate launch steps.
