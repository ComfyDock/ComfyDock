# Public Docs CLI Reference Audit

Scope: public CLI reference pages and inline command examples under
`docs/comfygit-docs`, compared against the current parser/source in
`packages/cli/comfygit_cli`.

This is a research scratch report for the docs redesign. It intentionally does
not rewrite generated docs or live public docs.

## 1. Current Reference Generation State

- The public reference pages appear to be generated once and then left stale.
  `docs/comfygit-docs/scripts/generate_cli_reference.py` imports
  `create_parser()` and writes Markdown directly into
  `docs/comfygit-docs/docs/cli-reference/`.
- The generator's command categories are incomplete and stale:
  - `global-commands` omits current top-level commands: `analyze`, `update`,
    `materialize`, `completion`, `orch`/`orchestrator`, and `workspace`.
  - `environment-commands` omits current commands: `overlay`, `serve`,
    `doctor`, `checkout`, `branch`, `switch`, `reset`, `merge`, `revert`,
    `manager`, and `metadata`.
  - `environment-commands` includes `rollback`, which is not present in the
    current parser.
  - `environment-commands` references `env-config local-sources`, but current
    `cli.py` only defines `env-config torch-backend` and `env-config extras`.
  - A `model-commands` category exists in the script but is skipped. MkDocs also
    has no model-specific CLI reference page even though `cg model` is large.
- The docs project has its own `docs/comfygit-docs/pyproject.toml`, while the
  CLI package is a uv workspace package at `packages/cli`. The generator
  prepends `packages/cli` to `sys.path`, which is the right source-layout path,
  but it still depends on import-time availability of CLI/runtime dependencies
  such as `argcomplete` and `comfygit-core`.
- Local note for this audit: I did not run the generator because repo-local
  `uv run` may be blocked by a root-owned `.venv` per task instructions. Source
  inspection was enough to identify the drift.

## 2. Missing Top-Level Commands/Subcommands In Public Docs

Missing or incomplete in `docs/comfygit-docs/docs/cli-reference/*.md` compared
to `packages/cli/comfygit_cli/cli.py`:

- Top-level global/workspace commands missing entirely:
  - `cg analyze <workflow> [--json] [--draft-spec] [--online] [-v] [-q]`
  - `cg update [--check]`
  - `cg materialize <source> --name <name> [--workspace PATH] [--models-dir PATH] [--branch REF] [--torch-backend BACKEND] [--models all|required|skip] [--with-manager] [--use] [--replace]`
  - `cg completion install|uninstall|status` is in the shell-completion page,
    but not generated into the main global reference.
  - `cg orch status|restart|kill|clean|logs` and alias `cg orchestrator ...`
  - `cg workspace cleanup [--force]`
- Environment commands missing entirely:
  - `cg overlay list|show|enable|disable|create`
  - `cg serve` with its studio/proxy/local state options.
  - `cg doctor [--check-only]`
  - `cg checkout`, `cg branch`, `cg switch`, `cg reset`, `cg merge`,
    `cg revert`
  - `cg manager status|update`
  - `cg metadata refresh`
- Existing reference entries missing newer options:
  - `cg create` and `cg import` omit `--no-manager`.
  - `cg run` and `cg sync` omit `--overlay`.
  - `cg node add` omits `--resolve-with-overlays`.
  - `cg model` omits `delete`.
  - `cg config` omits `--github-token`.
- Existing workflow reference is materially stale:
  - Public docs show `cg workflow model {importance}` only.
  - Current parser supports `cg workflow model list`, `add`, `remove`, and
    `importance`.
  - `cg workflow model add` requires a workflow name and either `--hash` or
    `--path`, plus optional `--importance/--criticality`.

## 3. Stale Or Invalid Command Examples In Public Docs

Representative invalid or stale examples found in inline docs:

- `cg rollback` examples appear throughout the public docs, but current parser
  has no `rollback` command. Use `cg reset`, `cg checkout`, or `cg revert`
  depending on the intended behavior.
  - `docs/comfygit-docs/docs/getting-started/concepts.md:251`
  - `docs/comfygit-docs/docs/user-guide/environments/version-control.md:234`
  - `docs/comfygit-docs/docs/user-guide/custom-nodes/managing-nodes.md:450`
  - `docs/comfygit-docs/docs/troubleshooting/environment-corruption.md:414`
- `cg logs` examples are invalid. Current parser has `cg debug` and
  `cg orch logs`; there is no top-level `logs` command.
  - `docs/comfygit-docs/docs/troubleshooting/common-issues.md:266`
  - `docs/comfygit-docs/docs/troubleshooting/common-issues.md:606`
  - `docs/comfygit-docs/docs/troubleshooting/common-issues.md:609`
- `cg workflow resolve --all` is invalid. Current parser requires one workflow
  name and does not expose `--all`.
  - `docs/comfygit-docs/docs/user-guide/collaboration/git-remotes.md:336`
  - `docs/comfygit-docs/docs/user-guide/collaboration/export-import.md:437`
  - `docs/comfygit-docs/docs/user-guide/collaboration/team-workflows.md:739`
- `cg node update --all` and `cg node update node-a node-b` are invalid.
  Current parser accepts exactly one `node_name`, plus `--yes` and `--no-test`.
  - `docs/comfygit-docs/docs/troubleshooting/common-issues.md:313`
  - `docs/comfygit-docs/docs/troubleshooting/common-issues.md:552`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:208`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:417`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:491`
  - `docs/comfygit-docs/docs/user-guide/custom-nodes/node-conflicts.md:565`
- `cg node update --check <node>` is invalid. Current parser has no `--check`
  option on node update.
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:138`
- `cg node list --verbose` is invalid. Current parser has no `--verbose` option
  for node list.
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:78`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:264`
- `cg repair --verbose` is invalid. Current parser supports `-y/--yes` and
  `--models`, but not `--verbose`.
  - `docs/comfygit-docs/docs/troubleshooting/common-issues.md:644`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:446`
- `cg constraint add -r constraints.txt` is invalid. Current parser does not
  support requirements-file input for constraints.
  - `docs/comfygit-docs/docs/user-guide/custom-nodes/node-conflicts.md:454`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:466`
- `cg pull origin` / `cg pull origin --force` examples are invalid because
  `pull` has no positional remote. Use `cg pull -r origin` or rely on default
  `origin`.
  - `docs/comfygit-docs/docs/user-guide/environments/version-control.md:374`
  - `docs/comfygit-docs/docs/user-guide/environments/version-control.md:391`
  - `docs/comfygit-docs/docs/user-guide/environments/version-control.md:420`
  - `docs/comfygit-docs/docs/troubleshooting/environment-corruption.md:364`
- `cg export my-env backup.tar.gz` is invalid. Export takes one optional output
  path; select an environment with `-e`.
  - `docs/comfygit-docs/docs/troubleshooting/environment-corruption.md:351`
  - `docs/comfygit-docs/docs/troubleshooting/environment-corruption.md:483`
- `cg export -o backup.tar.gz` is invalid. Export has no `-o`.
  - `docs/comfygit-docs/docs/troubleshooting/uv-errors.md:510`
- `cg -e fresh-env import backup.tar.gz` is conceptually wrong. `import` is a
  workspace-level command that creates/selects the target via `--name`, not an
  environment-scoped operation.
  - `docs/comfygit-docs/docs/troubleshooting/uv-errors.md:516`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:450`
- `cg sync --torch-backend cuda` is invalid/stale backend naming. Current help
  documents `auto`, `cpu`, `cu128`, `cu126`, `cu124`, `rocm6.3`, and `xpu`.
  - `docs/comfygit-docs/docs/troubleshooting/uv-errors.md:365`
- Several examples use old CUDA backend names such as `cu117` and `cu121`.
  These may still be meaningful historically, but current help examples no
  longer advertise them and public docs should avoid them unless explicitly
  documenting legacy environments.
  - `docs/comfygit-docs/docs/user-guide/custom-nodes/node-conflicts.md:130`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:104`
  - `docs/comfygit-docs/docs/troubleshooting/dependency-conflicts.md:513`
- Public docs frequently mention `comfyui-manager` as a package/node example.
  The current ComfyGit-managed manager package is `comfygit-manager`; examples
  involving removing/installing `comfyui-manager` should be rechecked for
  product intent before carrying them forward.

## 4. Generator/Tooling Fixes Needed Before Docs Rewrite

- Make CLI reference generation executable from the repo root without mutating
  a root-owned `.venv`. A safe path is either:
  - run from a docs-specific environment that installs the workspace CLI/core
    as editable dependencies, or
  - make the generator source-only enough to import the local parser with the
    repo workspace environment already set up.
- Update `categorize_commands()` so every current parser command appears in
  exactly one reference page. The category list should be derived or checked
  against the parser so missing commands fail generation.
- Remove `rollback` and `env-config local-sources` from generated references
  unless the parser reintroduces them.
- Add support for parser aliases. `orch` has alias `orchestrator`; docs should
  show one canonical command and mention the alias.
- Fix nested subcommand extraction so the generated output reliably captures
  newer groups like `workflow model list|add|remove|importance`,
  `manager status|update`, and `overlay ...`.
- Add a generated-docs freshness check in CI or a local `make docs-reference`
  target that fails when generated reference output differs from committed
  docs.
- Consider generating a machine-readable command inventory during docs builds
  and scanning public Markdown for obvious invalid examples such as
  `cg rollback`, `cg logs`, and `cg node update --all`.

## 5. Recommended Generated-Vs-Handwritten Boundary

- Generated:
  - Full CLI syntax, options, defaults, choices, aliases, and one-line help.
  - One page per command family.
  - No long narrative examples beyond minimal parser-derived usage.
- Handwritten:
  - Task flows such as "create and run an environment", "serve a workflow
    contract", "repair after pull", and "add a manual workflow model".
  - Opinionated examples that explain when to use a command.
  - Troubleshooting decision trees.
  - Compatibility notes, warnings, and workflow-level product semantics.
- Rule of thumb: if the page answers "what flags exist?", generate it. If it
  answers "what should I do next?", write it by hand and link to generated
  reference sections.

## 6. Safe Source-Of-Truth Command Examples

These examples match the current parser shape and are safe starting points for
rewritten docs, subject to behavioral review in the relevant domain pages:

```bash
uv tool install comfygit --upgrade
cg --version
cg init --models-dir ~/ComfyUI/models --yes
cg create my-env --torch-backend auto --use
cg -e my-env env-config torch-backend detect
cg -e my-env env-config torch-backend set cu128
cg -e my-env sync --overlay local-dev
cg -e my-env run --overlay local-dev
```

```bash
cg model index dir ~/ComfyUI/models
cg model index sync
cg model index find filmnet
cg model index show checkpoints/model.safetensors
cg model download <url> --path checkpoints/model.safetensors -y
cg model add-source <hash-or-filename> <url>
cg model delete <hash-or-filename> -y
```

```bash
cg -e my-env workflow list
cg -e my-env workflow resolve my-workflow --install
cg -e my-env workflow model list my-workflow
cg -e my-env workflow model add my-workflow --path frame_interpolation/film_net_fp16.safetensors --importance required
cg -e my-env workflow model remove my-workflow --path frame_interpolation/film_net_fp16.safetensors
cg -e my-env workflow model importance my-workflow <hash-or-filename> optional
```

```bash
cg -e my-env node add rgthree-comfy
cg -e my-env node add https://github.com/example/custom-node.git@main
cg -e my-env node dev-link comfygit-manager --path ../comfygit-manager --replace-existing
cg -e my-env node update rgthree-comfy --yes
cg -e my-env node remove rgthree-comfy --untrack
```

```bash
cg -e my-env commit -m "Add workflow dependencies"
cg -e my-env remote add origin git@github.com:team/my-env.git
cg -e my-env push
cg -e my-env pull -r origin --models required
cg -e my-env merge feature-branch --preview
cg -e my-env reset HEAD --mixed
cg -e my-env revert <commit>
```

```bash
cg export my-env.tar.gz
cg import my-env.tar.gz --name imported-env --models required --use
cg materialize https://github.com/team/my-env.git --name runtime-env --models required --torch-backend auto --replace
```

```bash
cg -e my-env serve --host 127.0.0.1 --port 8190 --comfy-url http://127.0.0.1:8188
cg -e my-env serve --role proxy --host 0.0.0.0 --port 8191 --proxy-token "$COMFYGIT_PROXY_TOKEN"
```

```bash
cg debug -n 100
cg debug --workspace
cg orch status --json
cg orch logs -n 100
cg manager status
cg manager update --version 0.1.2 -y
cg doctor --check-only
```

## 7. Open Questions/Risks

- `AGENTS.md` still lists `cg -e <env> env-config local-sources add ...` as a
  useful command, but current `cli.py` does not define `local-sources`. Decide
  whether docs should reflect the parser as-is, restore the command, or replace
  those examples with overlays/dev-link guidance.
- The public docs should clarify whether `rollback` is intentionally retired.
  If the product still wants a friendly rollback concept, it should either be
  implemented as an alias/wrapper or rewritten as a guide over `reset`,
  `checkout`, and `revert`.
- Some old CUDA backend examples may still work through lower layers even if
  parser help does not advertise them. The public docs should probably use
  current advertised backend names unless legacy backend support is explicitly
  promised.
- `cg serve` has many options that are internal/cloud-adjacent (`proxy`,
  callbacks, artifact localization). The generated reference should list them,
  but the handwritten guide should probably start with the simple local studio
  path and put proxy-runtime usage in an advanced section.
- `cg manager update` is valid, but users on broken manager versions may need
  manual Manager/ComfyUI registry update flows. CLI reference should avoid
  promising that self-update always succeeds; troubleshooting can explain the
  fallback.
