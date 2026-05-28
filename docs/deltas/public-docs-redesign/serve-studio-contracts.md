# Public Docs Redesign Audit: Serve, Studio, And Workflow Contracts

## 1. Scope and user story

This slice covers the path from a workflow authored in ComfyUI to a user-facing
Studio/API endpoint served by `cg serve`.

Primary user story:

1. A user builds and saves a workflow in ComfyUI.
2. In ComfyGit Manager, they define which workflow fields are public inputs and
   which output nodes become public outputs.
3. Manager saves a workflow execution contract and captures ComfyUI's native
   API-format prompt artifact.
4. The user commits/pushes/exports/materializes that environment.
5. `cg serve` hosts the packaged Studio UI plus contract-shaped endpoints that
   execute the saved contract against local ComfyUI or a proxy runtime.

The public docs should explain this as a normal product flow, not as internal
runtime plumbing. The important mental model is: Manager authors contracts,
core stores portable contract truth, and `cg serve` turns committed contracts
into a local/manual runtime surface.

## 2. Current public docs summary

The live docs currently have no real public story for `cg serve`, Studio,
workflow contracts, API prompt artifacts, upload refs, contract endpoints, or
proxy execution.

What exists today:

- `running-comfyui.md` explains `cg run` and ComfyUI access at
  `localhost:8188`, including long-running server advice, but it does not
  explain serving workflow contracts or the Studio UI
  (`docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:1`,
  `docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:24`,
  `docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:313`).
- Workflow docs cover saved workflow tracking and dependency resolution, but
  not API contracts or Manager-authored I/O mappings
  (`docs/comfygit-docs/docs/user-guide/workflows/workflow-tracking.md:1`,
  `docs/comfygit-docs/docs/user-guide/workflows/workflow-resolution.md:1`).
- Concepts explain `.cec/workflows/` and `pyproject.toml` but omit
  `.cec/workflow_api/`, execution contracts, Studio, and serve runtime state
  (`docs/comfygit-docs/docs/getting-started/concepts.md:61`,
  `docs/comfygit-docs/docs/getting-started/concepts.md:210`).

The docs therefore still teach "run ComfyUI" and "track workflows", but not
"publish a workflow-shaped API/Studio from a committed environment".

## 3. Truth-layer/code behavior that must be reflected

### Manager-authored contracts and API prompt artifacts

- Workflow execution contracts are tracked environment truth and should travel
  with workflow JSON plus a captured API prompt artifact when exported, pushed,
  materialized, or built
  (`docs/specs/workflow-contract-serving-lifecycle.md:10`).
- The supported authoring path is ComfyGit Manager inside ComfyUI. On save,
  Manager captures ComfyUI's API-format prompt and core writes it under
  `workflow_api/`
  (`docs/specs/workflow-contract-serving-lifecycle.md:27`,
  `docs/specs/workflow-contract-serving-lifecycle.md:42`).
- The editable UI workflow remains the human-authored artifact; the captured
  API prompt is the executable contract artifact
  (`docs/specs/environment-manifest-model.md:49`).
- CLI-only environments may run existing contracts, but are not the supported
  path for authoring new API-prompt-backed contracts
  (`docs/specs/environment-manifest-model.md:36`).
- Core must not regenerate API prompts from UI workflow JSON. Missing captured
  API prompt artifacts make a contract incomplete and should be repaired by
  re-saving in Manager
  (`docs/contracts/core/CONTRACT.md:151`,
  `packages/core/src/comfygit_core/services/workflow_execution.py:151`).
- The durable manifest model records named contracts, input/output definitions,
  `api_prompt_file`, provenance, and Manager/ComfyUI version fields
  (`packages/core/src/comfygit_core/models/workflow_contract.py:358`).

### `cg serve` runtime boundary

- Core owns transport-agnostic prompt/output semantics; HTTP routing, uploads,
  sessions, state, static Studio assets, proxying, and storage belong to
  adapters such as CLI serve
  (`docs/contracts/core/CONTRACT.md:119`,
  `docs/contracts/core/CONTRACT.md:131`).
- `cg serve` is the local/manual deployment replacement for the retired deploy
  package
  (`docs/specs/workflow-contract-serving-lifecycle.md:653`).
- CLI exposes `serve` with bind host/port, ComfyUI URL, role, executor, proxy,
  callback, artifact, request-size, state, gallery, and SQLite-state options
  (`packages/cli/comfygit_cli/cli.py:623`).
- `cg serve` does not launch ComfyUI; it points at an already running ComfyUI
  API URL
  (`docs/specs/workflow-contract-serving-lifecycle.md:158`,
  `packages/cli/comfygit_cli/serve_runtime.py:213`).

### Public Studio/API endpoints

Studio/front-door mode mounts:

- `GET /` packaged Studio SPA.
- `GET /health`.
- `GET /contracts`.
- `GET /contracts/{workflow}/{contract}`.
- `POST /contracts/{workflow}/{contract}/run`.
- Upload slot endpoints:
  `POST /uploads/prepare`, `PUT /uploads/{upload_id}`, and
  `GET /uploads/{upload_id}/status`.
- Gallery/run endpoints:
  `GET /gallery`, `DELETE /gallery/{item_id}`, `GET /runs`,
  `GET /runs/{run_id}`, and `POST /runs/{run_id}/cancel`.
- Output delivery via `GET /outputs/view`.

Code reference: `packages/cli/comfygit_cli/serve_runtime.py:249`.

Proxy runtime mode mounts only internal proxy endpoints:

- `GET /proxy/health`.
- `POST /proxy/runs`.
- `GET /proxy/runs/{prompt_id}`.
- `POST /proxy/runs/{prompt_id}/cancel`.
- `GET /proxy/artifacts/{artifact_id}`.

Code reference: `packages/cli/comfygit_cli/serve_runtime.py:280`.

### Upload/file-ref flow

- Large media inputs should use opaque `file_ref` values, not inline base64 or
  local paths
  (`docs/specs/workflow-contract-serving-lifecycle.md:771`).
- Current local implementation returns a `file_ref` from `POST /uploads/prepare`
  and `PUT /uploads/{upload_id}?token=...`
  (`packages/cli/comfygit_cli/serve_runtime.py:847`,
  `packages/cli/comfygit_cli/serve_runtime.py:870`).
- Serve resolves `file_ref` inputs for `image`, `audio`, `video`, and `file`
  contract types before patching the API prompt
  (`docs/specs/workflow-contract-serving-lifecycle.md:167`,
  `packages/cli/comfygit_cli/serve_runtime.py:52`).

### Local vs proxy execution

- `LocalComfyExecutor` submits prepared prompts to the configured ComfyUI API,
  waits for history when requested, extracts declared outputs, and can cancel by
  asking ComfyUI to delete/interrupt the prompt
  (`packages/cli/comfygit_cli/serve_executor.py:289`).
- `ProxyComfyExecutor` sends prepared prompts and staged uploads to a runtime
  `cg serve --role proxy`, then normalizes results back into the same public run
  shape
  (`packages/cli/comfygit_cli/serve_executor.py:345`).
- The front door owns public run IDs, gallery rows, upload refs, localized
  artifacts, and callbacks; the proxy is compute-only and internal
  (`docs/specs/workflow-contract-serving-lifecycle.md:410`,
  `docs/specs/workflow-contract-serving-lifecycle.md:462`,
  `docs/specs/workflow-contract-serving-lifecycle.md:564`).

### Runtime state and gallery

- Serve state is runtime adapter state, not portable manifest truth
  (`docs/specs/workflow-contract-serving-lifecycle.md:667`).
- Default state is ephemeral. `--state local` enables SQLite at the default
  workspace metadata path unless `--state-db` overrides it
  (`docs/specs/workflow-contract-serving-lifecycle.md:684`,
  `packages/cli/comfygit_cli/serve_runtime.py:544`).
- Gallery can be private anonymous-session scoped or shared across clients
  (`docs/specs/workflow-contract-serving-lifecycle.md:707`,
  `packages/cli/comfygit_cli/serve_runtime.py:1847`).
- State rows store metadata and artifact references, not large media bytes
  (`docs/specs/workflow-contract-serving-lifecycle.md:732`,
  `packages/cli/comfygit_cli/serve_state.py:1`).

## 4. Gaps/stale/misleading content with file references

- Missing top-level "Serve and Studio" guide. The nav has environment,
  workflow, model, node, and CLI sections but no serve/studio path
  (`docs/comfygit-docs/mkdocs.yml:36`).
- `running-comfyui.md` can make users think the only user-facing local web UI is
  raw ComfyUI at `localhost:8188`; it should point readers to `cg serve` when
  they want a workflow contract UI/API
  (`docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:75`).
- `concepts.md` omits `.cec/workflow_api/` and execution contracts from the
  environment layout and `pyproject.toml` explanation, which is now misleading
  for served workflows
  (`docs/comfygit-docs/docs/getting-started/concepts.md:61`,
  `docs/comfygit-docs/docs/getting-started/concepts.md:212`).
- Workflow docs explain tracking/resolution but not the separate "workflow
  contract" concept. This makes Manager's authoring role invisible
  (`docs/comfygit-docs/docs/user-guide/workflows/workflow-tracking.md:5`,
  `docs/comfygit-docs/docs/user-guide/workflows/workflow-resolution.md:5`).
- Public docs do not tell users that missing `workflow_api/*.api.json` files
  make contracts non-executable and must be repaired by re-saving in Manager
  (`packages/core/src/comfygit_core/services/workflow_execution.py:151`).
- CLI reference pages should include `cg serve` and its current options. The
  command is implemented but not represented in the current user-guide story
  (`packages/cli/comfygit_cli/cli.py:623`).
- Docs must avoid saying serve "deploys to cloud" or replaces hosted Cloud.
  Truth layer says open-source local/manual serving belongs to `cg serve`;
  provider-specific hosted deployment belongs to Cloud/external adapters
  (`docs/specs/workflow-contract-serving-lifecycle.md:653`).

## 5. Proposed public-doc pages/sections and where each concept should live

### Concepts page

Add a short "Workflow contracts" subsection:

- A saved workflow is the editable ComfyUI graph.
- A workflow contract is the public input/output shape for that graph.
- Manager authors contracts because it can inspect the loaded ComfyUI frontend
  graph and capture the native API prompt.
- `.cec/workflow_api/*.api.json` is portable tracked state when referenced by a
  contract.
- `cg serve` can run existing contracts without Manager after authoring.

Keep this conceptual and short. Do not list every endpoint here.

### New guide: Serve A Workflow As Studio/API

Suggested location:
`docs/comfygit-docs/docs/user-guide/serve-studio/serving-workflows.md`.

Content:

- Prerequisites: runnable environment, workflow tracked/committed, contract
  saved through Manager, ComfyUI running.
- Start ComfyUI with `cg run`.
- Start serve with `cg -e <env> serve --port 8190`.
- Open Studio at the serve URL.
- Run a contract from Studio.
- Run the same contract through HTTP.
- Explain default async run behavior, `wait: true`, runs, cancellation, and
  gallery.

### New guide: Authoring Workflow Contracts In Manager

Suggested location:
`docs/comfygit-docs/docs/user-guide/workflows/workflow-contracts.md`.

Content:

- What Manager captures.
- Why saved API prompts matter.
- Difference between UI workflow JSON and `workflow_api/*.api.json`.
- When to re-save: after changing mapped nodes, promoted subgraph widgets,
  input/output bindings, or workflow shape.
- What to commit: `pyproject.toml`, `.cec/workflows/*`, and
  `.cec/workflow_api/*`.

### New guide: Inputs, Uploads, And File Refs

Suggested location:
`docs/comfygit-docs/docs/user-guide/serve-studio/uploads.md`.

Content:

- Small scalar inputs go directly in JSON.
- Binary media uses upload slot flow.
- Clients submit `file_ref`, not local filesystem paths.
- Plain strings for media/file inputs mean "already accessible ComfyUI input
  filename" and are for advanced callers.

### New guide: Local And Proxy Executors

Suggested location:
`docs/comfygit-docs/docs/user-guide/serve-studio/executors.md`.

Content:

- Local executor: `cg serve -> ComfyUI`.
- Proxy executor: front-door `cg serve -> runtime cg serve --role proxy -> ComfyUI`.
- Use proxy mode for remote/ephemeral GPU experiments, not as the first local
  path.
- Front door owns public Studio/API state; proxy is internal compute.

### New reference: Serve HTTP API

Suggested location:
`docs/comfygit-docs/docs/cli-reference/serve-api.md` or
`docs/comfygit-docs/docs/reference/serve-api.md`.

Content:

- Endpoint table.
- Request/response examples.
- Session/gallery scoping notes.
- Error response shape examples.
- State persistence modes.

## 6. Safe command/API examples to publish

### Start local serve against local ComfyUI

```bash
# Terminal 1
cg -e my-env run

# Terminal 2
cg -e my-env serve --port 8190
```

For browser access from another machine, docs should mention binding to all
interfaces intentionally:

```bash
cg -e my-env serve --host 0.0.0.0 --port 8190
```

### Durable local gallery state

```bash
cg -e my-env serve --port 8190 --state local --gallery private
```

Shared local gallery:

```bash
cg -e my-env serve --port 8190 --state local --gallery shared
```

### List contracts

```bash
curl http://127.0.0.1:8190/contracts
```

### Run a scalar-input contract asynchronously

```bash
curl -X POST http://127.0.0.1:8190/contracts/my-workflow/default/run \
  -H 'content-type: application/json' \
  -d '{
    "inputs": {
      "prompt": "a cinematic photo of a glass greenhouse",
      "steps": 25
    }
  }'
```

Expected shape to document generically:

```json
{
  "status": "submitted",
  "run_id": "run_...",
  "prompt_id": "...",
  "output_slots": [],
  "gallery_items": []
}
```

### Poll a run

```bash
curl http://127.0.0.1:8190/runs/run_...
```

### Run synchronously for simple scripts

```bash
curl -X POST http://127.0.0.1:8190/contracts/my-workflow/default/run \
  -H 'content-type: application/json' \
  -d '{
    "wait": true,
    "inputs": {
      "prompt": "a small watercolor landscape"
    }
  }'
```

### Upload media and submit a file_ref

```bash
curl -X POST http://127.0.0.1:8190/uploads/prepare \
  -H 'content-type: application/json' \
  -d '{"filename": "input.png", "content_type": "image/png"}'
```

Use the returned `upload_url` and content type:

```bash
curl -X PUT 'http://127.0.0.1:8190/uploads/upload_...?token=...' \
  -H 'content-type: image/png' \
  --data-binary @input.png
```

Then submit the returned file ref:

```bash
curl -X POST http://127.0.0.1:8190/contracts/image-edit/default/run \
  -H 'content-type: application/json' \
  -d '{
    "inputs": {
      "input_image": {
        "kind": "file_ref",
        "ref": "upload_...",
        "filename": "input.png",
        "mime_type": "image/png"
      },
      "prompt": "make the sky sunset orange"
    }
  }'
```

### Local proxy validation

```bash
# Runtime proxy beside ComfyUI
cg -e my-env serve \
  --role proxy \
  --host 0.0.0.0 \
  --port 8792 \
  --comfy-url http://127.0.0.1:8188 \
  --proxy-token "$COMFYGIT_PROXY_TOKEN"

# Front door with Studio/API
cg -e my-env serve \
  --port 8791 \
  --executor proxy \
  --proxy-url http://127.0.0.1:8792 \
  --proxy-token "$COMFYGIT_PROXY_TOKEN"
```

For callback mode, publish only after docs clearly explain that
`--callback-url` must be reachable from the runtime proxy:

```bash
cg -e my-env serve \
  --port 8791 \
  --executor proxy \
  --proxy-url http://127.0.0.1:8792 \
  --proxy-token "$COMFYGIT_PROXY_TOKEN" \
  --callback-url http://127.0.0.1:8791
```

## 7. Open questions/risks

- The truth layer says serve runtime has moved toward captured API prompt
  artifacts, but CGSERVE-RUN-01 still contains wording about "legacy
  prompt-building logic" and says the adapter should move to stored artifacts
  before stable runtime. Code now calls `build_manifest_contract_prompt`, which
  requires `api_prompt_file`. The spec should be tightened before final public
  docs use strong "stable" language.
- Public docs should not imply Manager is optional for authoring. It is optional
  only after a contract has been authored and committed with its API prompt
  artifact.
- Endpoint examples should stay labelled "local API surface" until auth,
  remote state, and hosted Cloud endpoint policy are documented separately.
- Proxy/callback examples are powerful but easy to misuse. They should be in an
  advanced page, not the first getting-started serve guide.
- Upload MIME/extension policy is intentionally permissive today. Avoid
  promising strict validation beyond request-size/path-safety behavior.
- The public docs need a product-language decision: whether to call this
  "Studio", "Contract Studio", or "Serve Studio" consistently across CLI,
  Manager, Cloud, and docs.
- This audit did not inspect the sibling `comfygit-manager` repo. Before final
  docs describe Manager UI button labels or exact authoring clicks, verify them
  against the Manager source and a running panel.
