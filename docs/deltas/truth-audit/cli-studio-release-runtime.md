# CLI, Studio, Release, And Serve Runtime Truth Audit

Scope: CLI boundary and UX guarantees, `cg serve` runtime and Studio static
packaging, Studio source/dist relationship, release/version lockstep for
core/CLI/Studio, retired deploy package, and manager release ordering as it
appears in this repo.

This is an audit scratch file, not normative truth.

## Current Behavior Summary

### CLI Boundary

- The CLI is an argparse shell over `comfygit-core`, exposed through both
  `comfygit` and `cg` entry points in `packages/cli/pyproject.toml`.
- Command routing lives in `packages/cli/comfygit_cli/cli.py`; environment
  commands route to `EnvironmentCommands`, workspace commands route to
  `GlobalCommands`, and completion/update helpers remain CLI-owned.
- `packages/cli/docs/architecture.md` states the intended boundary clearly:
  CLI is presentation and interaction, while domain policy belongs in core.
- The CLI owns user-facing output, shell completion, interactive strategies,
  update notices, progress callbacks, logging decorators, and error formatting.
- The CLI has some legitimate runtime adapter code in `serve_runtime.py`,
  `serve_executor.py`, and `serve_state.py`; that runtime code intentionally
  depends on `aiohttp`, SQLite, static browser assets, and ComfyUI HTTP APIs
  outside core.

### CLI Update UX

- `cg update --check` reads PyPI metadata for `comfygit`, compares against the
  installed CLI version, prints a one-line notice when newer, and links GitHub
  releases.
- `cg update` chooses `uv tool upgrade comfygit` when the installed package
  appears to live under a uv tools directory and `uv` is available; otherwise it
  falls back to `python -m pip install --upgrade comfygit` when pip is
  available.
- Background update notices are CLI-only, best-effort, interactive-only,
  disabled in CI/non-TTY sessions, cached under `~/.config/comfygit`, and
  suppressible with `COMFYGIT_NO_UPDATE_CHECK`.
- The update checker is not core behavior and should not become a manifest or
  environment invariant.

### `cg serve` Runtime

- `cg serve` is an environment command with default bind
  `127.0.0.1:8190`, default ComfyUI API URL `http://127.0.0.1:8188`,
  default role `studio`, executor `local`, request limit `256 MiB`, run timeout
  `12h`, state `ephemeral`, and gallery `private`.
- `cg serve --role studio` creates an `aiohttp` front door with:
  - static Studio hosting at `/` and `/assets/`
  - `/health`
  - `/contracts`
  - `/contracts/{workflow}/{contract}`
  - upload slot endpoints
  - gallery endpoints
  - run list/detail/cancel endpoints
  - worker callback endpoint
  - contract run endpoint
  - output view proxy
  - SPA fallback
- `cg serve --role proxy` creates a compute-only proxy app with only
  `/proxy/health`, `/proxy/runs`, `/proxy/runs/{prompt_id}`,
  `/proxy/runs/{prompt_id}/cancel`, and `/proxy/artifacts/{artifact_id}`.
- Runtime state is adapter-owned, not portable manifest truth. It is stored in
  memory by default or in SQLite with `--state local`; the default SQLite path
  is under workspace metadata unless overridden by `--state-db`.
- Studio gallery scope is session-private by default and shared with
  `--gallery shared`.
- Local execution submits prepared contract prompts to the configured ComfyUI
  API, waits for history when needed, extracts declared outputs, probes media
  dimensions, and exposes outputs through serve-owned URLs.
- Proxy execution is already implemented as a configurable executor mode:
  front-door serve submits prepared prompts and staged uploads to a runtime
  proxy, can use callback mode for serverless-style completion, and localizes
  proxy artifacts before persisting run/gallery records.
- `cg serve` does not launch ComfyUI; `cg run`, container entrypoints, or a
  deployment adapter must provide the backing runtime.

### Studio Source And Packaged Static Assets

- `packages/studio` is a private Vite/React package named
  `@comfygit/studio`; it is versioned even though it is not published as a
  Python package.
- `packages/studio/vite.config.ts` builds to `packages/studio/dist/static`
  with `base: "./"` so the static bundle can be served from a Python package
  or from hosted endpoint paths.
- `dev/scripts/sync-studio-static.py` copies the built Studio output into
  `packages/cli/comfygit_cli/studio_static`.
- `make build-studio`, `make build-cli`, and `make build-all` all build Studio
  and sync the static output into the CLI package before building the CLI wheel.
- `serve_runtime._studio_static_dir()` resolves packaged static assets from
  the installed `comfygit_cli` package via `importlib.resources`.
- `studio_index_handler` injects `window.__COMFYGIT_STUDIO_CONFIG__` with an
  empty API base path for local `cg serve`, auth mode `none`, and the
  environment name. Studio code also supports host-provided runtime config for
  endpoint deployments.
- If packaged static assets are missing, `cg serve` returns a fallback HTML
  page that says Studio assets are not built.

### Release And Version Lockstep

- The release artifacts currently use lockstep version `0.4.2`:
  - `packages/core/pyproject.toml`: `comfygit-core==0.4.2`
  - `packages/cli/pyproject.toml`: `comfygit==0.4.2`
  - `packages/studio/package.json`: `@comfygit/studio@0.4.2`
- The CLI pins `comfygit-core==<same version>` in its Python dependencies.
- `make show-versions` displays all three release artifact versions.
- `make bump-version VERSION=<version>` updates core, CLI, the CLI core pin,
  and Studio package version.
- `dev/scripts/check-versions.py` enforces exact version equality across core,
  CLI, and Studio.
- `.github/workflows/publish.yml` runs on manual dispatch and pushes to `main`
  that touch the version files. It validates lockstep versions, skips if both
  Python packages are already on PyPI, publishes core first, waits for core to
  become visible on PyPI, builds/syncs Studio into the CLI package, publishes
  the CLI, waits for the CLI on PyPI, and creates a GitHub release.
- Release notes list the core package, CLI package, and bundled Studio version.

### Retired Deploy Package

- `packages/deploy` is absent from the current package tree.
- `AGENTS.md` and `CLAUDE.md` state that `packages/deploy` /
  `comfygit-deploy` is retired and must not be re-added to workspace members,
  lockstep versioning, tests, build targets, or publish workflows.
- Current repo tooling and workflow search did not show active package/build
  references to `packages/deploy`.
- The active open-source runtime path is `cg serve`; hosted deployment belongs
  to ComfyGit Cloud outside this repo.

### Manager Release Ordering

- This repo does not own manager publication, but `AGENTS.md` documents the
  ordering dependency: publish `comfygit-core==<version>` to PyPI first, then
  the sibling `comfygit-manager` repo can pin that exact core version and
  publish its ComfyUI registry release.
- The current root publish workflow only publishes core, CLI, bundled Studio,
  and a GitHub release for this repo.
- There is no normative release spec in `docs/contracts` or `docs/specs`
  covering manager ordering; the source of truth is currently agent/process
  documentation.

## Key Code Paths And Tests

### Code Paths

- CLI entry points and parser:
  - `packages/cli/pyproject.toml`
  - `packages/cli/comfygit_cli/cli.py`
- CLI serve command handoff:
  - `packages/cli/comfygit_cli/cli.py`
  - `packages/cli/comfygit_cli/env_commands.py`
- Serve runtime HTTP apps, static Studio hosting, health, upload, run, gallery,
  callback, and output handlers:
  - `packages/cli/comfygit_cli/serve_runtime.py`
- Serve executor boundary and local/proxy execution:
  - `packages/cli/comfygit_cli/serve_executor.py`
- Serve runtime state:
  - `packages/cli/comfygit_cli/serve_state.py`
- CLI update behavior:
  - `packages/cli/comfygit_cli/update_commands.py`
  - `packages/cli/comfygit_cli/utils/update_checker.py`
  - `packages/cli/comfygit_cli/utils/update_notice.py`
- Studio package and runtime config:
  - `packages/studio/package.json`
  - `packages/studio/vite.config.ts`
  - `packages/studio/src/lib/runtime-config.ts`
  - `packages/studio/src/lib/api.ts`
- Static sync and version tooling:
  - `Makefile`
  - `dev/scripts/sync-studio-static.py`
  - `dev/scripts/check-versions.py`
- Release workflow:
  - `.github/workflows/publish.yml`

### Tests

- `packages/cli/tests/test_serve_command.py`
  - parser defaults/options
  - command-to-config handoff
  - root Studio app serving
  - local and proxy executor behavior
  - proxy runtime API
  - callback artifact upload
  - environment ref health
  - deferred proxy health probe
  - output range proxying
  - SQLite persistence
  - active run recovery
  - gallery session scoping
  - run detail/cancel endpoints
  - local executor submission/cancel/error handling
  - upload slot and file-ref input preparation
- `packages/cli/tests/test_update_checker.py`
  - PyPI check caching
  - environment-variable disable
  - notification persistence
- `packages/cli/tests/test_update_command.py`
  - `cg update --check`
  - uv-tool upgrade preference
- `packages/cli/tests/test_update_notice.py`
  - async notice printing behavior
- `packages/cli/tests/test_no_manager_flags.py`
  - create/import `--no-manager` handoff
- Missing or not found in this audit:
  - direct tests for `dev/scripts/check-versions.py`
  - direct tests for `dev/scripts/sync-studio-static.py`
  - workflow-level tests for `.github/workflows/publish.yml`
  - direct clause-ID references in CLI serve tests

## Existing Clause Coverage

### Covered Well

- `CGCORE-EXEC-01`: Core owns stored workflow contract execution semantics.
- `CGCORE-EXEC-02`: Core should stay transport-agnostic.
- `CGCORE-EXEC-03`: `cg serve` is a runtime adapter over stored contract
  semantics.
- `CGSERVE-RUN-01`: `cg serve` fronts ComfyUI with contract-shaped endpoints.
- `CGSERVE-RUN-01B`: Studio frontend is a shared packaged static asset.
- `CGSERVE-RUN-02`: Serve can run without Manager after authoring.
- `CGSERVE-RUN-03`: Serve owns transport and lifecycle concerns.
- `CGSERVE-RUN-05` through `CGSERVE-RUN-06G`: executor strategy, local/proxy
  execution, proxy health, callback coordination, and artifact upload.
- `CGSERVE-STATE-*`: serve-owned state, SQLite, gallery policy, artifact refs.
- `CGSERVE-IN-*`: upload refs, upload slots, local/proxy input staging.
- `CGSERVE-OUT-*`: output delivery and proxy output localization.
- `CGMAT-CMD-07`: materialization does not launch `cg serve`.

### Partially Covered Or Mismatched

- `CGCORE-EXEC-02` and `CGCORE-EXEC-03` are marked `PLANNED`, but the current
  implementation already keeps core free of `aiohttp`, SQLite serve state, and
  Studio static assets while implementing `cg serve` in the CLI package. These
  may now be `LIVE` or `PARTIAL` depending on how strict the team wants to be
  about "core contract execution services" being fully typed and stable.
- `CGSERVE-RUN-01A` is marked `PLANNED`, but the root route now serves the
  Studio SPA from packaged static assets. This should probably become
  `PARTIAL`, because there is a real UI, but the clause's full "cards" wording
  may not exactly match the current UI shape.
- `CGSERVE-RUN-05` says executor selection is not exposed and proxy execution is
  not implemented. That is stale: `--executor {local,proxy}`, `--role proxy`,
  `ProxyComfyExecutor`, and proxy runtime endpoints exist.
- `CGSERVE-RUN-05C` says recovery still uses one pending gallery item per run,
  while later code/tests indicate output slots now exist and are persisted. This
  clause should be refreshed to avoid misleading future refactors.
- `CGSERVE-RUN-06` is still written partly as future direction even though
  local proxy mode, callback mode, staged uploads, localized artifacts, and
  health refs exist. The status can stay `PARTIAL`, but the current
  implementation paragraph should be treated as the stable baseline.
- `CGSERVE-RUN-01B` covers shared Studio packaging, but it does not explicitly
  say the CLI wheel must contain synced built static output produced from the
  same source version. That invariant currently lives in Makefile/tooling and
  AGENTS.
- Release lockstep and publish ordering are not covered by normative truth
  docs. They live in `AGENTS.md`, `Makefile`, `dev/scripts/check-versions.py`,
  and `.github/workflows/publish.yml`.
- The retired deploy package is not covered by normative truth docs. It lives
  in `AGENTS.md` / `CLAUDE.md`.
- Manager release ordering is not covered by normative truth docs. It lives in
  `AGENTS.md` only.
- `.github/workflows/README.md` and `.github/workflows/SETUP.md` appear stale:
  they describe separate `publish-core.yml` / `publish-cli.yml` workflows and
  old package names, while the active workflow is `.github/workflows/publish.yml`
  and the package artifacts are `comfygit-core`, `comfygit`, and bundled
  `@comfygit/studio`.

## Gaps And Risks

- Release safety depends on process/tooling, but there is no normative release
  spec. Future agents could change versions, workflow order, or Studio static
  packaging without tripping a truth-layer contradiction.
- The CLI/Studio relationship is real product behavior, not just build detail:
  users installing the CLI expect `cg serve` to host Studio without Node.js.
  That should be a truth-layer promise.
- The retired deploy package decision is documented for agents but not in a
  clause. Without a clause, reintroducing deploy into workspace/build/publish
  tooling would only violate AGENTS, not the normative docs.
- Manager release ordering matters because Manager pins/loads core. Keeping this
  only in AGENTS makes it easy to publish Manager against a core version that is
  not yet available on PyPI.
- Some serve clauses have stale "future" or "not implemented" statements that
  understate current behavior. That creates refactor risk because readers may
  treat implemented behavior as optional.
- Test coverage is strong for serve runtime behavior, but most tests do not
  reference clause IDs. Clause traceability would improve if the highest-value
  tests had comments/docstrings or module-level markers referencing the updated
  clauses.

## Proposed New Or Changed Clauses

Suggested locations are intentionally conservative. This audit should feed a
single-owner truth-layer edit pass.

### In `docs/contracts/core/CONTRACT.md`

#### CGCORE-EXEC-02 [LIVE]: Core contract execution stays transport-agnostic

Suggested change: promote from `PLANNED` to `LIVE` if the team accepts the
current code boundary as the promise. Core does not import or own `aiohttp`,
SQLite serve state, Studio static assets, runtime sessions, or HTTP routing.

Validation: STATIC

Evidence:
- `packages/cli/comfygit_cli/serve_runtime.py`
- `packages/cli/comfygit_cli/serve_executor.py`
- `packages/cli/comfygit_cli/serve_state.py`
- absence of serve transport dependencies from core package dependencies

#### CGCORE-EXEC-03 [PARTIAL]: `cg serve` is a runtime adapter over stored contract semantics

Suggested change: promote from `PLANNED` to `PARTIAL` and update wording from
"future serve runtime" to "the CLI serve runtime". Keep `PARTIAL` because
stored API prompt execution, typed core execution APIs, event streams, and
provider adapters still have gaps.

Validation: MIXED

Evidence:
- `packages/cli/tests/test_serve_command.py`
- `docs/specs/workflow-contract-serving-lifecycle.md`

### In `docs/specs/workflow-contract-serving-lifecycle.md`

#### CGSERVE-RUN-01A [PARTIAL]: `cg serve` root hosts the contract Studio UI

Suggested change: promote from `PLANNED` to `PARTIAL`. The root and SPA
fallback serve packaged Studio today, but the exact UI capabilities should be
described as current behavior rather than old "first studio slice" intent.

Validation: TEST

Evidence:
- `serve_runtime.create_app`
- `serve_runtime.studio_index_handler`
- `packages/cli/tests/test_serve_app_serves_contract_studio_root`

#### CGSERVE-RUN-01B [PARTIAL]: Studio frontend is a shared packaged static asset

Suggested change: keep `PARTIAL`, but add explicit release/build invariants:
Studio source lives in `packages/studio`, builds to `dist/static`, release
tooling copies that output into `packages/cli/comfygit_cli/studio_static`, and
the CLI wheel should serve that synced static output without requiring Node.js
at runtime.

Validation: STATIC

Evidence:
- `packages/studio/vite.config.ts`
- `dev/scripts/sync-studio-static.py`
- `Makefile`
- `packages/cli/comfygit_cli/serve_runtime.py`

#### CGSERVE-RUN-05 [PARTIAL]: Contract execution is selected through a serve-owned executor strategy

Suggested change: refresh stale implementation text. Executor selection is now
user-facing through `--executor local|proxy`; runtime role is user-facing
through `--role studio|proxy`; proxy execution is implemented but still partial
because event streams, stronger auth policy, remote object storage, and provider
launch sugar remain future work.

Validation: MIXED

Evidence:
- `packages/cli/comfygit_cli/cli.py`
- `packages/cli/comfygit_cli/serve_executor.py`
- `packages/cli/tests/test_serve_command.py`

#### CGSERVE-RUN-05C [PARTIAL]: Studio should recover active runs after refresh

Suggested change: update the current implementation paragraph to say output
slots are now persisted and returned from run detail state. Remove the stale
"one pending gallery item per run" line unless that still applies to a specific
legacy path.

Validation: MIXED

Evidence:
- `ServeRunOutputSlot`
- `SQLiteServeStateStore`
- `test_active_run_recovery_completes_persisted_run`
- `test_serve_single_run_endpoint_returns_slots_and_gallery_items`

#### CGSERVE-RUN-07 [PARTIAL]: `cg serve` is the local/manual deployment replacement for the retired deploy package

Suggested new clause. The open-source repo should treat `cg serve` as the local
runtime/serving path. Hosted deployment provider orchestration belongs to
ComfyGit Cloud, not to a revived `packages/deploy` package.

Validation: HUMAN_REVIEW

Suggested text:

```md
### CGSERVE-RUN-07 [PARTIAL]: `cg serve` is the local/manual deployment replacement for the retired deploy package
Validation: HUMAN_REVIEW

The open-source ComfyGit monorepo should expose local and manually hosted
runtime execution through `cg serve`. Provider-specific hosted deployment
orchestration belongs to ComfyGit Cloud or external adapters, not to a revived
`packages/deploy` package in this workspace.

`packages/deploy` and `comfygit-deploy` are retired. They must not be restored
as workspace members, release artifacts, build targets, publish targets, or
maintained package APIs unless the truth layer is intentionally revised first.
```

### New release spec: `docs/specs/release-lifecycle.md`

#### CGREL-LOCK-01 [LIVE]: Core, CLI, and bundled Studio use lockstep release versions

Validation: STATIC

Suggested text:

```md
### CGREL-LOCK-01 [LIVE]: Core, CLI, and bundled Studio use lockstep release versions
Validation: STATIC

Every ComfyGit monorepo release uses one version for `comfygit-core`,
`comfygit`, and `@comfygit/studio`. The CLI package must pin
`comfygit-core==<same version>` and release checks must fail when these versions
diverge.
```

Evidence:
- `Makefile`
- `dev/scripts/check-versions.py`
- `.github/workflows/publish.yml`
- package version files

#### CGREL-STUDIO-01 [LIVE]: CLI releases include the built Studio static bundle

Validation: STATIC

Suggested text:

```md
### CGREL-STUDIO-01 [LIVE]: CLI releases include the built Studio static bundle
Validation: STATIC

The Studio source package is not a runtime dependency of the installed CLI.
Before building or publishing the CLI release artifact, release tooling must
build `packages/studio`, sync the emitted static assets into
`packages/cli/comfygit_cli/studio_static`, and package those assets with the CLI
wheel so `cg serve` can host Studio without Node.js.
```

Evidence:
- `Makefile build-cli/build-all`
- `.github/workflows/publish.yml`
- `dev/scripts/sync-studio-static.py`
- `serve_runtime._studio_static_dir`

#### CGREL-PUB-01 [LIVE]: Core is published before the CLI

Validation: STATIC

Suggested text:

```md
### CGREL-PUB-01 [LIVE]: Core is published before the CLI
Validation: STATIC

Because the CLI pins `comfygit-core==<release version>`, the release workflow
must publish `comfygit-core` first and wait until that version is visible on
PyPI before building and publishing `comfygit`.
```

Evidence:
- `.github/workflows/publish.yml`

#### CGREL-MGR-01 [PARTIAL]: Manager releases depend on published core versions

Validation: HUMAN_REVIEW

Suggested text:

```md
### CGREL-MGR-01 [PARTIAL]: Manager releases depend on published core versions
Validation: HUMAN_REVIEW

The ComfyGit Manager release is owned by the sibling manager repository, but it
must not pin or publish against a `comfygit-core` version that is unavailable on
PyPI. Manager release preparation should happen after the corresponding core
release is published and visible.
```

Rationale:
- This repo cannot enforce the manager registry release directly, so status
  should be `PARTIAL` unless cross-repo CI is added.

#### CGREL-DEPLOY-01 [LIVE]: `comfygit-deploy` is retired from this monorepo release surface

Validation: STATIC

Suggested text:

```md
### CGREL-DEPLOY-01 [LIVE]: `comfygit-deploy` is retired from this monorepo release surface
Validation: STATIC

`packages/deploy` and `comfygit-deploy` are not release artifacts in this
monorepo. Release tooling, version checks, build targets, tests, workspace
members, and publish workflows must not treat deploy as an active package.
Local/manual serving belongs to `cg serve`; hosted provider deployment belongs
to ComfyGit Cloud or external adapters.
```

Evidence:
- absence of `packages/deploy`
- absence of active deploy package references in root package/build workflow
- `AGENTS.md` / `CLAUDE.md`

#### CGREL-WF-01 [PARTIAL]: Release process docs should match the active publish workflow

Validation: STATIC

Suggested text:

```md
### CGREL-WF-01 [PARTIAL]: Release process docs should match the active publish workflow
Validation: STATIC

Repository release docs and agent instructions should describe the active
workflow names, package names, release artifact order, and required validation.
Stale release docs that point at removed workflows or old package names must be
treated as maintenance gaps because they can cause incorrect release execution.
```

Evidence:
- `.github/workflows/README.md`
- `.github/workflows/SETUP.md`
- `.github/workflows/publish.yml`

## Tests That Should Reference Clauses

Add clause IDs as comments or docstrings to focused tests as they are touched.
Do not churn every test just for traceability.

- `packages/cli/tests/test_serve_command.py`
  - `test_serve_app_serves_contract_studio_root`
    - `CGSERVE-RUN-01A`
    - `CGREL-STUDIO-01`
  - `test_serve_parser_defaults`
    - `CGSERVE-RUN-01`
    - `CGSERVE-STATE-02`
    - `CGSERVE-STATE-03`
  - `test_serve_parser_accepts_runtime_options`
    - `CGSERVE-RUN-05`
    - `CGSERVE-RUN-06`
  - `test_proxy_runtime_app_submits_and_exposes_artifact`
    - `CGSERVE-RUN-06A`
    - `CGSERVE-RUN-06B`
  - `test_proxy_runtime_app_pushes_callback_artifacts`
    - `CGSERVE-RUN-06F`
    - `CGSERVE-RUN-06G`
  - `test_worker_callback_endpoint_records_uploaded_artifact`
    - `CGSERVE-RUN-06E`
    - `CGSERVE-RUN-06G`
  - `test_proxy_health_reports_environment_ref`
    - `CGSERVE-RUN-06D`
  - `test_frontdoor_proxy_health_defers_remote_probe_by_default`
    - `CGSERVE-RUN-06D`
  - `test_sqlite_state_store_persists_gallery_items`
    - `CGSERVE-STATE-02`
  - `test_serve_gallery_is_scoped_by_session_cookie`
    - `CGSERVE-STATE-03`
  - `test_serve_single_run_endpoint_returns_slots_and_gallery_items`
    - `CGSERVE-RUN-05B`
    - `CGSERVE-RUN-05C`
  - `test_serve_cancel_run_endpoint_marks_pending_outputs_cancelled_and_removes_gallery_items`
    - `CGSERVE-RUN-05E`
  - `test_upload_slot_writes_to_comfyui_input_dir`
    - `CGSERVE-IN-02`
    - `CGSERVE-IN-03`
  - `test_prepare_contract_inputs_resolves_file_refs`
    - `CGSERVE-IN-01`
    - `CGSERVE-IN-05`
  - `test_output_view_proxies_byte_range_headers`
    - `CGSERVE-OUT-01`

- `packages/cli/tests/test_update_checker.py`
  - `test_update_checker_caches_for_24h`
    - proposed `CGCLI-UPD-01` if a CLI UX spec is added
  - `test_update_checker_respects_no_update_env`
    - proposed `CGCLI-UPD-01`

- `packages/cli/tests/test_update_command.py`
  - `test_cg_update_prefers_uv_tool_when_detected`
    - proposed `CGCLI-UPD-02` if updater behavior becomes normative

- New focused tests to consider:
  - `dev/scripts/check-versions.py` rejects mismatched core/CLI/Studio
    versions: `CGREL-LOCK-01`.
  - `dev/scripts/sync-studio-static.py` replaces CLI static assets from
    Studio build output: `CGREL-STUDIO-01`.
  - static workflow check or lightweight script confirming publish workflow
    order is core -> wait -> Studio build/sync -> CLI: `CGREL-PUB-01`.

## Recommended Integration Order

1. Add `docs/specs/release-lifecycle.md` with the release/Studio/deploy/manager
   clauses above. This is the largest uncovered surface and highest release
   safety value.
2. Refresh stale statuses/text in `CGCORE-EXEC-02`, `CGCORE-EXEC-03`,
   `CGSERVE-RUN-01A`, `CGSERVE-RUN-05`, and `CGSERVE-RUN-05C`.
3. Expand `CGSERVE-RUN-01B` to explicitly cover built Studio static assets in
   the CLI wheel.
4. Either update or retire stale `.github/workflows/README.md` and
   `.github/workflows/SETUP.md` so they no longer contradict the active
   publish workflow.
5. Add clause references only to high-value tests that are naturally touched by
   the above edits.
