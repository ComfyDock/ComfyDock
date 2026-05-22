# Public Docs Redesign Audit: Environment And Runtime Slice

## 1. Scope and user story

This slice covers the user-facing path from "I have ComfyGit installed" to "I
can create, run, sync, repair, share, and materialize a reproducible ComfyUI
environment."

The public docs should help users understand:

- A workspace is machine-local coordination state for environments, models, cache,
  logs, and active-env selection.
- An environment has portable tracked truth plus derived runtime state.
- The tracked manifest repository is what should be committed, exported, pushed,
  imported, and materialized.
- `cg run`, `cg sync`, `cg repair`, and Git handoff operations reconcile the
  runtime toward the manifest plus local machine configuration.
- PyTorch backend selection, local editable sources, and local overlays are
  runtime inputs, not portable manifest truth.
- `cg materialize` is the non-interactive runtime/build hydration path; it is not
  the same as human-oriented import.

## 2. Current public docs summary

The current docs have a useful early product skeleton:

- Concepts introduce workspaces, environments, `.cec/`, manifest sections,
  Git/export sharing, model hashing, node resolution, and active environments
  (`docs/comfygit-docs/docs/getting-started/concepts.md:18`,
  `docs/comfygit-docs/docs/getting-started/concepts.md:55`,
  `docs/comfygit-docs/docs/getting-started/concepts.md:100`).
- Features gives a command inventory for environment creation, active env,
  run/status/delete, Git operations, export/import, model indexing, workflows,
  Python deps, and config (`docs/comfygit-docs/docs/getting-started/features.md:5`,
  `docs/comfygit-docs/docs/getting-started/features.md:101`).
- Workspaces covers `cg init`, `COMFYGIT_HOME`, `cg config`, registry cache, logs,
  workspace layout, multiple workspaces, and model directory setup
  (`docs/comfygit-docs/docs/user-guide/workspaces.md:11`,
  `docs/comfygit-docs/docs/user-guide/workspaces.md:57`,
  `docs/comfygit-docs/docs/user-guide/workspaces.md:151`).
- Environment pages cover `cg create`, `cg run`, ComfyUI args, commit/history,
  rollback-style narratives, remotes, pull, and repair
  (`docs/comfygit-docs/docs/user-guide/environments/creating-environments.md:11`,
  `docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:10`,
  `docs/comfygit-docs/docs/user-guide/environments/version-control.md:1`).
- Collaboration pages cover export/import, Git imports, Git remotes, pull model
  strategies, conflict handling, and team patterns
  (`docs/comfygit-docs/docs/user-guide/collaboration/export-import.md:1`,
  `docs/comfygit-docs/docs/user-guide/collaboration/git-remotes.md:1`,
  `docs/comfygit-docs/docs/user-guide/collaboration/team-workflows.md:1`).

The shape is broad, but it reflects an older "version control for ComfyUI"
story more than the current "portable manifest plus local runtime hydration"
story.

## 3. Truth-layer/code behavior that must be reflected

- `pyproject.toml` is the portable manifest authority, with ComfyGit metadata
  under `[tool.comfygit]` (`docs/specs/environment-manifest-model.md:8`,
  `docs/specs/environment-manifest-model.md:15`; `docs/contracts/core/CONTRACT.md:54`).
- Runtime state is derived: ComfyUI checkout, venv, node directories, symlinks,
  caches, generated databases, and model bytes are not authoritative portable
  truth (`docs/contracts/core/CONTRACT.md:68`,
  `docs/specs/environment-manifest-model.md:100`).
- Machine-local configuration is not committed manifest truth. PyTorch backend
  and local uv/source overrides are injected during sync/run
  (`docs/contracts/core/CONTRACT.md:61`,
  `docs/specs/environment-sync-lifecycle.md:218`).
- `sync` may recreate the venv; manual package installs into `.venv` are
  disposable unless captured in manifest dependencies or local injection config
  (`docs/specs/environment-sync-lifecycle.md:14`,
  `docs/contracts/core/CONTRACT.md:182`).
- `run` syncs unless explicitly bypassed, forwards ComfyUI args, and supervises
  restart/environment-switch lifecycle (`docs/specs/environment-sync-lifecycle.md:21`,
  `docs/specs/environment-sync-lifecycle.md:260`; `packages/cli/comfygit_cli/env_commands.py:668`).
- `repair` is meant to restore derived state from manifest, lockfile, and local
  config (`docs/specs/environment-sync-lifecycle.md:28`;
  `packages/cli/comfygit_cli/cli.py:720`).
- Local overlays are temporary dependency injection. Local and activation files
  are machine-local; shared non-local overlays may be portable source files
  (`docs/specs/environment-sync-lifecycle.md:199`,
  `packages/cli/comfygit_cli/cli.py:567`).
- Overlay order and PyTorch precedence are defined; operation-level
  `--torch-backend` on sync/run/pull is one-time and should not rewrite the saved
  `.pytorch-backend` file (`docs/specs/environment-sync-lifecycle.md:210`,
  `docs/specs/environment-sync-lifecycle.md:218`;
  `packages/cli/comfygit_cli/cli.py:594`, `packages/cli/comfygit_cli/cli.py:743`,
  `packages/cli/comfygit_cli/cli.py:842`).
- Git handoff operations such as checkout, reset, switch, merge, revert, and pull
  should reconcile nodes, packages, uv state, local PyTorch/overlay injection, and
  workflows after tracked state changes (`docs/specs/environment-sync-lifecycle.md:242`,
  `docs/specs/environment-sync-lifecycle.md:248`).
- Export bundles include portable recipe files, captured API prompts, workflows,
  package config, and shared overlays, but not `uv.lock`, local overlays, model
  bytes, or bundled dev-node source (`packages/core/src/comfygit_core/managers/export_import_manager.py:39`,
  `packages/core/src/comfygit_core/managers/export_import_manager.py:45`,
  `packages/core/src/comfygit_core/managers/export_import_manager.py:64`,
  `packages/core/src/comfygit_core/managers/export_import_manager.py:73`,
  `packages/core/src/comfygit_core/managers/export_import_manager.py:81`).
- `cg materialize SOURCE --name <env>` is top-level, non-interactive, and aimed
  at Docker, CI, remote machines, and API-serving containers
  (`docs/specs/environment-materialization-lifecycle.md:14`,
  `packages/cli/comfygit_cli/cli.py:260`).
- Materialize defaults are runtime-safe: `--models skip`, no Manager unless
  `--with-manager`, `auto` torch backend, fail on sync errors, and no import
  commit (`docs/specs/environment-materialization-lifecycle.md:34`,
  `packages/cli/comfygit_cli/global_commands.py:780`).
- Materialize supports Git, bundle, and directory sources; directory sources copy
  only portable recipe files and explicitly exclude `.git`, `.venv`, `.complete`,
  caches, local overlays, runtime checkouts, DBs, logs, and model bytes
  (`docs/specs/environment-materialization-lifecycle.md:51`,
  `docs/specs/environment-materialization-lifecycle.md:59`).

## 4. Gaps/stale/misleading content with file references

- The public docs do not mention `cg materialize` in this slice. That leaves no
  user-facing explanation of the runtime/build hydration path, despite the command
  being top-level and truth-layered (`packages/cli/comfygit_cli/cli.py:260`;
  `docs/specs/environment-materialization-lifecycle.md:7`).
- Concepts show PyTorch backend configuration as `[tool.uv]`/`[tool.uv.sources]`
  inside tracked `pyproject.toml` (`docs/comfygit-docs/docs/getting-started/concepts.md:193`).
  Current behavior stores backend selection in `.pytorch-backend` and injects it
  locally during sync/run (`docs/contracts/core/CONTRACT.md:61`;
  `packages/core/src/comfygit_core/factories/environment_factory.py:587`).
- Environment creation says the default Python is 3.12
  (`docs/comfygit-docs/docs/user-guide/environments/creating-environments.md:21`),
  while the parser default is currently 3.11
  (`packages/cli/comfygit_cli/cli.py:479`).
- Creation internals say ComfyGit writes PyTorch download indexes to
  `pyproject.toml` (`docs/comfygit-docs/docs/user-guide/environments/creating-environments.md:252`).
  This should be rewritten around `.pytorch-backend`, generated PyTorch overlays,
  and local injection.
- Export/import says `uv.lock` is part of the export payload
  (`docs/comfygit-docs/docs/user-guide/collaboration/export-import.md:66`), but
  export code explicitly does not include it because PyTorch variants are
  platform-specific (`packages/core/src/comfygit_core/managers/export_import_manager.py:45`).
- Concepts say export/import includes "Development node source code"
  (`docs/comfygit-docs/docs/getting-started/concepts.md:260`). Current export
  explicitly does not bundle dev nodes; portable dev nodes rely on git provenance
  (`packages/core/src/comfygit_core/managers/export_import_manager.py:81`;
  `docs/contracts/core/CONTRACT.md:352`).
- Import docs say PyTorch import updates `pyproject.toml` with backend config and
  locks versions there (`docs/comfygit-docs/docs/user-guide/collaboration/export-import.md:357`,
  `docs/comfygit-docs/docs/user-guide/collaboration/export-import.md:370`,
  `docs/comfygit-docs/docs/user-guide/collaboration/export-import.md:384`).
  The public docs should instead explain saved `.pytorch-backend`, one-time
  overrides, and local re-resolution.
- The environment docs still teach `cg rollback` heavily
  (`docs/comfygit-docs/docs/user-guide/environments/version-control.md:227`),
  but the visible parser exposes `checkout`, `reset`, `revert`, `switch`, and
  `pull`; no `rollback` parser entry appears in the current CLI surface inspected
  (`packages/cli/comfygit_cli/cli.py:791`, `packages/cli/comfygit_cli/cli.py:812`,
  `packages/cli/comfygit_cli/cli.py:837`).
- Version-control docs use stale positional remote syntax such as `cg push origin`
  and `cg pull origin` (`docs/comfygit-docs/docs/user-guide/environments/version-control.md:329`,
  `docs/comfygit-docs/docs/user-guide/environments/version-control.md:374`).
  Current parser uses `-r/--remote`, with `origin` default
  (`packages/cli/comfygit_cli/cli.py:842`, `packages/cli/comfygit_cli/cli.py:890`).
- Running docs say ComfyGit passes all arguments after `run` directly to ComfyUI
  and show `cg run --port`, `cg run --listen`, `cg run --auto-launch`, and
  `cg run --cpu` as direct examples
  (`docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:183`).
  Parser handling is more precise: ComfyGit owns known flags and unknown args are
  passed through; using `--` is the safest docs pattern for ComfyUI args
  (`packages/cli/comfygit_cli/cli.py:95`,
  `docs/comfygit-docs/docs/user-guide/environments/running-comfyui.md:29`).
- The docs do not explain `env-config torch-backend show|set|detect`,
  `env-config extras`, `overlay list/show/enable/disable/create`, or one-time
  `--overlay` use as first-class local runtime configuration
  (`packages/cli/comfygit_cli/cli.py:513`,
  `packages/cli/comfygit_cli/cli.py:567`).
- Workspaces still end with "Coming soon" links even though the linked docs exist
  (`docs/comfygit-docs/docs/user-guide/workspaces.md:245`).

## 5. Proposed public-doc pages/sections and where each concept should live

- `getting-started/concepts.md`
  - Keep high-level mental model only.
  - Add "portable truth vs derived runtime state" as the core environment model.
  - Explain workspace, environment repository, manifest, local config, runtime
    checkout/venv, model index, and materialization in one narrative.
  - Remove deep TOML examples that are likely to drift; link to a manifest
    reference page instead.

- `user-guide/environments/creating-environments.md`
  - Cover `cg create`, `--python`, `--comfyui`, `--torch-backend`, `--no-manager`,
    `--use`, and what gets initialized.
  - Correct default Python.
  - Explain completion marker/incomplete cleanup at a user level: failed creates
    are hidden/cleaned up instead of being listed as real envs.

- New or revised `user-guide/environments/local-runtime-config.md`
  - Home for `.pytorch-backend`, `cg env-config torch-backend`, default sync
    extras, overlays, local vs shared overlays, and one-time overrides.
  - This should be separate from portable manifest docs to reduce confusion.

- `user-guide/environments/running-comfyui.md`
  - Keep simple `cg run` story.
  - Make `cg run -- --port 8189` and `cg run -- --listen 0.0.0.0` the safe
    pass-through examples.
  - Add `--no-sync` as an advanced escape hatch.
  - Mention that normal run syncs first and uses active local config.

- New or revised `user-guide/environments/sync-and-repair.md`
  - Distinguish `cg sync` from `cg repair`.
  - Explain venv recreation, manifest-driven reconciliation, workflow restore,
    node reconciliation, model link/download strategies, and when to use repair.

- `user-guide/environments/version-control.md`
  - Rename or reshape around "Environment History And Branches."
  - Use current commands: `commit`, `log`, `checkout`, `branch`, `switch`, `reset`,
    `merge`, `revert`.
  - Move push/pull/remotes to collaboration docs to avoid duplication.

- `user-guide/collaboration/git-remotes.md`
  - Keep as the canonical page for remotes, push, pull, branch/ref handoff, and
    conflict recovery.
  - Update syntax to `cg remote add`, `cg pull -r origin`, `cg push -r origin`.
  - Explain that pull and tree-changing Git operations reconcile runtime state.
  - Add one sentence that Git remotes share manifest/workflow truth, not model bytes.

- `user-guide/collaboration/export-import.md`
  - Keep as human handoff/import page.
  - Correct export payload: no `uv.lock`, no model bytes, no dev-node source,
    includes `workflow_api/` and shared overlays.
  - Explain import as authoring setup: may install/register Manager unless
    `--no-manager`, may create import commit, and has softer sync handling than
    materialize.

- New `user-guide/collaboration/materialize.md` or `user-guide/runtime/materialize.md`
  - Canonical user-facing page for `cg materialize`.
  - Frame it as Docker/CI/remote-machine hydration from Git, tarball, or directory.
  - Show runtime-safe defaults and how to opt into models and Manager.
  - Explicit non-goal: it does not launch ComfyUI or `cg serve`.

- Generated CLI reference
  - Regenerate or repair generated command docs from `cli.py`.
  - Narrative guides should link to reference for exhaustive flags.

## 6. Safe command examples to publish

These examples match the parser/code inspected here. `uv run cg ... -h` could
not be executed in this checkout because `.venv/bin/python3` is root-owned and
canonicalization failed with permission denied, so examples below are based on
`packages/cli/comfygit_cli/cli.py`.

```bash
# Workspace and environment basics
cg init
cg init /path/to/workspace --models-dir /path/to/models
cg create my-env --python 3.11 --torch-backend auto --use
cg create headless-env --no-manager
cg list
cg use my-env
cg status
```

```bash
# Run and sync with local runtime inputs
cg run
cg run -- --port 8189
cg run -- --listen 0.0.0.0
cg run --no-sync
cg sync
cg sync --torch-backend cu128
cg sync --extra cuda
cg sync --overlay my-overlay
cg repair --models required
```

```bash
# Environment-local runtime configuration
cg env-config torch-backend show
cg env-config torch-backend detect
cg env-config torch-backend set cu128
cg env-config extras show
cg env-config extras add cuda
cg env-config extras remove cuda
```

```bash
# Dependency overlays
cg overlay list
cg overlay list --active
cg overlay create my-overlay
cg overlay create --local
cg overlay show my-overlay
cg overlay enable my-overlay
cg overlay disable my-overlay
```

```bash
# Manifest/history/handoff
cg manifest
cg manifest --section tool.comfygit.nodes
cg commit -m "Add workflow dependencies"
cg log
cg checkout <ref>
cg switch main
cg pull -r origin --models required
cg pull -r origin --preview
cg push -r origin
cg push -r origin --force
```

```bash
# Human import/export
cg export my-env.tar.gz
cg export my-env.tar.gz --allow-issues
cg import my-env.tar.gz --name imported-env --use
cg import https://github.com/team/comfy-env.git --name team-env --branch main
cg import my-env.tar.gz --name headless-import --no-manager --models skip
```

```bash
# Headless/runtime materialization
cg materialize ./environment-recipe --name runtime-env
cg materialize https://github.com/team/comfy-env.git --name runtime-env --branch main
cg materialize my-env.tar.gz --name runtime-env --workspace /srv/comfygit --models-dir /models
cg materialize my-env.tar.gz --name runtime-env --models required --torch-backend cu128
cg materialize my-env.tar.gz --name authoring-copy --with-manager --use
cg materialize my-env.tar.gz --name runtime-env --replace
```

## 7. Open questions/risks

- The docs need a decision on whether public examples should use `cg run --port`
  shorthand or always teach `cg run -- --port`. The parser currently passes
  unknown args through, but `--` is safer and clearer when ComfyGit grows new
  run flags.
- The current docs have a large rollback narrative, but the current parser
  inspected here did not expose `rollback`. Decide whether to remove it,
  document `checkout/reset/revert`, or confirm a compatibility alias exists
  elsewhere before editing public docs.
- `uv.lock` handling needs a deliberate public explanation. The docs currently
  sell lockfile portability, while export intentionally omits `uv.lock` for
  platform-specific PyTorch reasons. This should be phrased carefully so users
  understand what is reproducible versus locally re-resolved.
- Import and materialize share setup internals but should not be merged in the
  docs. Import is for an editable authoring environment; materialize is for
  non-interactive runtime/build hydration. Mixing them will confuse Cloud,
  Docker, and hosted-runtime docs later.
- Help-command smoke could not run from this checkout due root-owned `.venv`.
  Before final public rewrite, run CLI help from a clean/dev shell and regenerate
  the CLI reference from the actual parser.
