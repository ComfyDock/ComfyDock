# Container Runtime Command Delta

Status: planned implementation direction for the ComfyGit CLI package.

This delta captures the intended shape for first-class `cg container ...`
commands. It is package-local truth: the CLI owns container process UX and
engine adaptation, while core continues to own reusable environment,
manifest, sync, readiness, and run-plan semantics.

## Motivation

ComfyGit development and validation already use containerized ComfyUI
runtimes, mostly through manager-owned Docker scripts. Those scripts are useful
for local development, but they are not a stable user-facing CLI surface and
they can create host permission problems when root-owned containers run `uv` or
write into bind-mounted repositories.

The CLI should provide a small, explicit container surface for users and
developers who want to run a ComfyGit environment in an isolated local runtime
without learning repo-specific scripts.

## Planned Clauses

### CGCLI-CONTAINER-01 [PLANNED]: Container commands are CLI adapter behavior
Validation: LLM_REVIEW

The `cg container ...` command family belongs in `packages/cli`, not
`packages/core`. Core may expose typed environment, readiness, sync, and run
planning APIs that the CLI uses, but Docker, Podman, terminal UX, process
streaming, and command-line engine flags remain CLI adapter concerns.

### CGCLI-CONTAINER-02 [PLANNED]: Engine selection is explicit and pluggable
Validation: TEST

Container commands support an engine abstraction instead of hard-coding Docker.
The first engines are Docker and Podman. Engine choice is resolved in this
order:

1. command flag, such as `--engine docker` or `--engine podman`
2. environment variable, such as `COMFYGIT_CONTAINER_ENGINE`
3. saved CLI configuration, if added later
4. auto-detection

An optional binary override, such as `COMFYGIT_CONTAINER_BIN`, may point to a
non-standard `docker` or `podman` executable.

### CGCLI-CONTAINER-03 [PLANNED]: The engine boundary uses typed run specs
Validation: STATIC

The CLI engine adapter accepts a typed run specification instead of building
long command strings throughout command handlers. The run spec includes image,
name, command, environment variables, ports, mounts, working directory, user,
groups, GPU request, memory, shared memory, labels, and detach policy.

Engine implementations translate that typed spec into concrete Docker or
Podman command-line arguments.

### CGCLI-CONTAINER-04 [PLANNED]: Host user identity is the default for bind mounts
Validation: TEST

On Linux, container runs default to the current host UID and GID so files
created in bind-mounted workspaces, repositories, model directories, and custom
node checkouts remain editable by the host user.

The CLI exposes identity controls:

- `--user current` for the default host UID/GID behavior
- `--user image` to use the image default user
- `--user root` for deliberate root execution
- `--uid` and `--gid` for explicit identity overrides
- optional supplemental group controls when needed for device or shared
  directory access

Docker adapters map the default to `--user UID:GID`. Podman rootless adapters
prefer `--userns=keep-id` when available.

### CGCLI-CONTAINER-05 [PLANNED]: Runtime images support arbitrary non-root users
Validation: TEST

ComfyGit runtime images do not assume the process runs as root or as a fixed
named user. They provide writable runtime locations through environment
variables or explicit mounts, including `HOME`, `XDG_CACHE_HOME`,
`UV_CACHE_DIR`, and any ComfyGit workspace/cache paths used by the command.

Startup logic must not repair permissions by recursively rewriting mounted
host paths unless the user explicitly asks for that behavior.

### CGCLI-CONTAINER-06 [PLANNED]: Containerized commands avoid root-owned repo venvs
Validation: TEST

Containerized development commands must not run `uv` in a bind-mounted source
repository as root using that repository's default `.venv`. If an editable
source checkout is mounted, the CLI either runs as the host UID/GID or points
`UV_PROJECT_ENVIRONMENT` at a container-local path.

Local editable ComfyGit package paths should continue to use environment
overlays rather than persistent mutation of managed virtualenvs.

### CGCLI-CONTAINER-07 [PLANNED]: GPU requests use ComfyGit-level vocabulary
Validation: TEST

Users request GPU behavior with ComfyGit-level options such as `--gpu all`,
`--gpu none`, or future typed GPU selectors. Engine adapters translate that
request into provider-specific flags.

Docker may translate `--gpu all` to `--gpus all` plus NVIDIA environment
variables. Podman may translate it to CDI device flags, such as
`--device nvidia.com/gpu=all`, when supported by the host.

### CGCLI-CONTAINER-08 [PLANNED]: The MVP uses direct engine commands
Validation: LLM_REVIEW

The first implementation uses direct `docker` or `podman` CLI subprocesses
rather than Docker SDKs, Podman SDKs, Docker Compose, or Podman Compose. Compose
files may remain useful for repo-local development stacks, but the public CLI
container surface should start from a portable run-spec-to-engine-command
adapter.

### CGCLI-CONTAINER-09 [PLANNED]: Runtime and development mounts are distinct
Validation: LLM_REVIEW

The CLI distinguishes normal runtime mounts from development mounts. Runtime
mounts cover the ComfyGit workspace, model directories, caches, and exposed
ports needed to run an environment. Development mounts cover editable package
checkouts, custom node source directories, SSH agent sockets, Git credentials,
or other local authoring state.

Development mounts are opt-in and should not be required for ordinary users to
run a committed environment.

### CGCLI-CONTAINER-10 [PLANNED]: Container commands are observable and reversible
Validation: TEST

The command family exposes safe lifecycle operations before adding advanced
deployment flows:

- `cg container doctor` inspects engine availability, rootless/rootful mode,
  GPU support, current UID/GID, and likely bind-mount permission risks.
- `cg container run` starts an environment runtime.
- `cg container status` describes matching ComfyGit-managed containers.
- `cg container logs` streams logs.
- `cg container shell` opens a shell in a running container.
- `cg container stop` stops a ComfyGit-managed container without deleting
  user-owned workspaces or model directories.

Future commands such as containerized `serve` or proxy roles should build on
the same engine adapter and identity model.

### CGCLI-CONTAINER-11 [PLANNED]: Container defaults avoid privileged host access
Validation: STATIC

Container commands do not mount the host Docker socket by default and do not
require privileged containers for ordinary ComfyGit runtime use. Where engines
support it, commands prefer `no-new-privileges` style hardening unless it
conflicts with required GPU/device access.

## Proposed Package Shape

```text
packages/cli/comfygit_cli/container/
  __init__.py
  commands.py          # argparse handlers and user-facing output
  engine.py            # ContainerEngine protocol and shared models
  docker.py            # DockerEngine implementation
  podman.py            # PodmanEngine implementation
  detection.py         # engine and GPU capability detection
  specs.py             # typed run specs and identity/GPU enums
```

This package may call public `comfygit_core` APIs for workspace/environment
state and run planning, but it should not import core managers or repositories
directly.

## Explicit Non-Goals

- Do not move Docker or Podman execution into core.
- Do not require Compose for the first public container command.
- Do not require manager development scripts for ordinary container runs.
- Do not mount host container-engine sockets by default.
- Do not repair bind-mount ownership by silently rewriting host paths.
- Do not make development-node mounts part of the default user runtime path.

## Implementation Order

1. Add `cg container doctor` with engine detection, UID/GID reporting, and GPU
   capability hints.
2. Add the typed `ContainerRunSpec` and Docker/Podman argument renderers with
   tests.
3. Add `cg container run` for one ComfyGit environment, with explicit workspace,
   models, port, engine, user, and GPU options.
4. Add lifecycle commands: `status`, `logs`, `shell`, and `stop`.
5. Add containerized `serve` and proxy-oriented roles only after the base
   runtime path is stable.
6. Revisit manager-owned development scripts and decide whether they should
   delegate to the public CLI container surface.

## Validation Expectations

Implementation PRs should include:

- unit tests for engine selection precedence
- unit tests for Docker and Podman argument rendering
- tests proving host UID/GID is the Linux default
- tests proving `--user image`, `--user root`, `--uid`, and `--gid` alter the
  run spec as expected
- tests proving containerized dev commands avoid root-owned repository `.venv`
  creation
- a manual smoke note for at least one Docker-backed GPU runtime on
  `akatzfeyserver` when GPU execution behavior changes
