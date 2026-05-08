# Delta Dossier: Serverless Proxy Developer Lifecycle

## Purpose

This dossier captures the development and validation flow ComfyGit should prove
next for moving a locally authored ComfyUI environment into disposable remote
compute behind `cg serve` proxy execution.

This is not normative product truth. It is a bounded test plan and architecture
working note for validating that an authored ComfyGit environment can be
materialized into a clean runtime, exposed through a compute-only proxy, and
used by the same front-door Studio/API surface that already works locally.

## Related Clauses

- CGSERVE-RUN-06
- CGSERVE-RUN-06A
- CGSERVE-RUN-06B
- CGSERVE-RUN-06C
- CGSERVE-IN-05
- CGSERVE-OUT-03

## Current Evidence

- Code:
  - `packages/cli/comfygit_cli/serve_executor.py`
  - `packages/cli/comfygit_cli/serve_runtime.py`
  - `packages/cli/comfygit_cli/cli.py`
  - `packages/cli/comfygit_cli/env_commands.py`
  - `packages/cli/tests/test_serve_command.py`
- Specs:
  - `docs/specs/workflow-contract-serving-lifecycle.md`
- Local validation:
  - A Studio/front-door `cg serve` process can run with `--executor proxy`.
  - A compute-only runtime proxy can run with `--role proxy`.
  - The front door can submit a contract run to the proxy, poll completion,
    stream the produced artifact back, persist run/gallery/output-slot records,
    and serve the localized artifact after completion.

## Developer Lifecycle To Prove

### 1. Author Locally

The user starts in a normal authoring environment, usually a Docker container
with:

- ComfyUI running through `cg run`.
- ComfyGit Manager installed for workflow and contract authoring.
- Models mounted into the container.
- A ComfyGit workspace mounted into the container.

The authoring loop is:

1. Build or edit ComfyUI workflows.
2. Map contract inputs and outputs in Manager.
3. Run local `cg serve` against the same ComfyUI instance.
4. Open ComfyGit Studio.
5. Generate through the contract and verify request shape, output mapping,
   gallery behavior, cancellation, uploads, and artifact rendering.

This stage proves that the workflow contract is valid against the local
authoring environment.

### 2. Reproduce In A Clean Local Runtime Container

After local authoring works, the environment should be exported as a tarball or
pushed to a Git remote. Then a separate clean container should materialize that
source.

The clean runtime container should:

- Start from the same runtime base image family.
- Mount the model directory or model volume.
- Mount or create its own ComfyGit workspace.
- Materialize the authored environment from Git or export tarball.
- Run `cg run` to boot ComfyUI.
- Run `cg serve --role proxy` beside ComfyUI.

The original authoring/front-door side should then run:

```bash
cg -e <authoring-env> serve \
  --executor proxy \
  --proxy-url http://<runtime-container-host>:<proxy-port> \
  --proxy-token <token>
```

The expected user experience in Studio should match local executor mode:

- contracts load from the front door;
- generation creates pending output slots;
- run duration and status are tracked by the front door;
- cancellation routes through the proxy;
- completed artifacts are copied back to front-door serve storage;
- Studio history loads from front-door state and does not depend on the runtime
  container after artifact localization.

This stage proves that the environment is portable and that proxy execution is
not accidentally relying on the authoring container's ComfyUI process.

### 3. Stage The Runtime On Modal

Once local clean-container reproduction works, the next stage is a Modal staging
runtime.

The first Modal target should use a simple base image that contains enough
system dependencies to install and run ComfyGit and ComfyUI. It should attach a
named Modal volume and run materialization against that volume.

The staging process should:

1. Start the base image on a GPU class suitable for setup validation.
2. Attach the named volume for workspace, environment, custom-node cache, and
   model cache.
3. Materialize the exported or Git-backed ComfyGit environment.
4. Download or verify required models into the volume.
5. Start `cg run` against the materialized environment.
6. Start `cg serve --role proxy --comfy-url http://127.0.0.1:<comfy-port>`.
7. Verify `/proxy/health` reports ComfyUI available.

The important property is that the expensive first-time work is stored on the
volume. Repeated invocations should reuse the materialized environment and model
cache instead of rebuilding everything from scratch.

### 4. Execute Through Disposable Remote Compute

After Modal staging works, the front door should stay local or on a cheap
always-on host while Modal provides disposable execution.

The target runtime shape is:

```text
browser or API client
  -> front-door cg serve + Studio + local state
      -> ProxyComfyExecutor
          -> Modal runtime proxy
              -> ComfyUI
                  -> generated artifacts
          <- proxy artifact bytes
      -> localized artifact cache + SQLite run/gallery state
```

The expected behavior is:

- The front door owns contracts, sessions, run ids, output slots, gallery rows,
  uploaded file refs, and localized artifact refs.
- The Modal runtime owns only compute, runtime-local input staging, ComfyUI
  submission, status, cancellation, and temporary artifact exposure.
- When a run completes, the front door copies image/video/audio artifacts from
  Modal before recording durable gallery output.
- After localization, the Modal worker can shut down without breaking Studio
  history.
- If Modal dies before localization, the front door should mark the run failed
  or retry in a later implementation; completed localized outputs remain safe.

## Reference Commands

Local authoring serve:

```bash
cg -e <authoring-env> serve \
  --host 0.0.0.0 \
  --port <front-door-port> \
  --comfy-url http://127.0.0.1:<local-comfy-port> \
  --state local
```

Local runtime proxy beside ComfyUI:

```bash
cg -e <runtime-env> serve \
  --role proxy \
  --host 0.0.0.0 \
  --port <proxy-port> \
  --comfy-url http://127.0.0.1:<runtime-comfy-port> \
  --proxy-token <token>
```

Front door pointing at the runtime proxy:

```bash
cg -e <authoring-env> serve \
  --host 0.0.0.0 \
  --port <front-door-port> \
  --state local \
  --executor proxy \
  --proxy-url http://<runtime-host>:<proxy-port> \
  --proxy-token <token>
```

## Validation Checklist

### Local Authoring

- Contract list loads in Studio.
- Contract input defaults render correctly.
- Image, audio, video, and file upload inputs use upload refs rather than inline
  base64.
- Successful runs create output slots and gallery items.
- Failed runs preserve useful raw API output and error messages.
- Cancelled runs remove pending placeholders and mark the run cancelled.

### Clean Local Runtime Container

- Materialize from Git or export tarball succeeds in a clean workspace.
- `cg run` starts ComfyUI from the materialized environment.
- `cg serve --role proxy` starts beside ComfyUI.
- Front-door `--executor proxy` health reports proxy and ComfyUI available.
- A contract generation through the front door completes through the runtime
  proxy.
- Front-door artifact URLs use localized `/outputs/view?serve_artifact=...`
  refs, not proxy URLs.
- Runtime proxy can be stopped after completion and previously localized media
  still loads from the front door.

### Modal Staging

- The base image can install or run ComfyGit without manual mutation.
- The Modal volume receives the materialized environment and model cache.
- First materialization may be slow, but repeated startup reuses the volume.
- ComfyUI starts on the chosen GPU shape.
- Runtime proxy health can be reached from the front door.

### Modal Execution

- Front-door Studio can start a run through the Modal proxy.
- Upload refs are staged into Modal's ComfyUI input directory.
- Run status reaches submitted, running, and completed or error.
- Cancellation reaches the Modal proxy and interrupts queued/running work.
- Image, video, and audio outputs stream back to the front door.
- Localized media survives remote worker shutdown.

## Risks And Unknowns

- Cold starts may dominate perceived latency because ComfyUI and model loading
  are expensive.
- Volume reuse must match the image ABI: Python, CUDA, PyTorch, OS libraries,
  and custom-node compiled dependencies must stay compatible.
- Some custom nodes may write outputs in unexpected places or require additional
  runtime-local files.
- Modal endpoint lifetime must cover prompt submission, status polling,
  cancellation, and artifact fetch.
- Shared bearer-token auth is sufficient for the prototype but not a final
  multi-user deployment auth model.
- If remote execution dies before artifact localization, the front door does not
  yet have durable remote recovery semantics.

## Non-Goals

- Do not build a full Modal product deployment in this dossier.
- Do not add S3/R2/object-storage adapters in this slice.
- Do not add SSE/progress streaming as a prerequisite for the first Modal proof.
- Do not redesign Manager authoring or contract mapping.
- Do not require `cg run` to own proxy launch until the independent two-process
  setup is proven.
- Do not treat this as a replacement for the normative serve lifecycle spec.

## Likely Implementation Follow-Ups

- Add a repeatable local two-container proxy smoke script.
- Add a Modal staging script that materializes an environment into a named
  volume.
- Add a Modal runtime proxy example that boots ComfyUI and `cg serve --role
  proxy`.
- Add stronger proxy auth and deployment token handling.
- Add remote-run failure and retry semantics after the basic Modal loop works.
- Add event streaming for progress once the run/proxy lifecycle is stable.
