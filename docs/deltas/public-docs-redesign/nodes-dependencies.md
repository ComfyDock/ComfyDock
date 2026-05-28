# Nodes And Dependencies Public Docs Audit

## 1. Scope and user story

This slice covers how a user installs, updates, removes, develops, and
troubleshoots custom nodes and their Python dependencies.

The public-doc story should help users answer:

- How do I add a node from the ComfyUI Registry or a Git repository?
- How do I work on a local custom node without breaking portable environment
  identity?
- What gets tracked in the manifest, what stays local, and what gets installed
  into the venv?
- How do node dependency groups, uv constraints, optional extras, overlays, and
  local sources interact?
- What does "optional" mean for a custom node, and who is allowed to mark a node
  optional?
- How do I update or recover `comfygit-manager` without confusing it with
  ComfyUI-Manager?

## 2. Current public docs summary

The current docs already have useful first-pass material:

- `adding-nodes.md` explains registry adds, GitHub URLs, batch installs,
  `--dev`, `--force`, `--no-test`, tracked metadata, requirements scanning, and
  cache behavior.
- `managing-nodes.md` explains `node list`, `node update`, `node remove`, and
  `node prune`, including the important point that development-node removal
  leaves files alone.
- `node-conflicts.md`, `dependency-conflicts.md`, `uv-errors.md`, and the Python
  dependency docs explain uv conflicts, constraints, optional extras, and
  CUDA/no-build-isolation cases.

The problem is drift. These pages read like an older CLI/reference snapshot, not
the current node/dependency contract. They also duplicate conflict-resolution
guidance across several pages, which increases the chance of stale commands.

## 3. Truth-layer/code behavior that must be reflected

- The manifest is the portable source of truth for node package metadata,
  Python dependency state, workflows, and model metadata
  (`docs/contracts/core/CONTRACT.md:54`, `docs/contracts/core/CONTRACT.md:182`).
- Registry, Git URL, and local development nodes are distinct source cases;
  local development paths are not portable by themselves
  (`docs/specs/environment-manifest-model.md:118`).
- Development nodes can be portable when they record repository URL and pinned
  commit; branch is context, pinned commit is preferred for exact
  reconstruction (`docs/specs/environment-manifest-model.md:125`,
  `docs/contracts/core/CONTRACT.md:352`).
- Workflow node dependencies should persist canonical manifest package IDs, not
  display names, directory names, repository URLs, or other local aliases
  (`docs/specs/environment-manifest-model.md:134`,
  `docs/contracts/core/CONTRACT.md:380`).
- Installed-node aliases are exact and local. Ambiguous alias matches must stay
  unresolved instead of being guessed (`docs/contracts/core/CONTRACT.md:380`).
- Custom node criticality is `required` or `optional`; missing criticality reads
  as `required` (`docs/specs/dependency-criticality.md:31`,
  `docs/specs/dependency-criticality.md:39`,
  `packages/core/src/comfygit_core/models/shared.py:14`).
- Workflow graph usage is advisory only. Graph analysis must not silently mark a
  node optional or required (`docs/specs/dependency-criticality.md:45`,
  `docs/contracts/core/CONTRACT.md:254`).
- Optional node support is partial: manifest storage and local readiness exist,
  but centralized build/deploy consumption is still in progress
  (`docs/specs/environment-manifest-model.md:157`,
  `docs/contracts/core/CONTRACT.md:244`).
- `node add` performs dependency preflight by default, probes dependencies when
  not in strict mode, may discover constraints, and applies changes inside a
  rollback-aware transaction (`packages/core/src/comfygit_core/managers/node_manager.py:312`,
  `packages/core/src/comfygit_core/managers/node_manager.py:484`,
  `packages/core/src/comfygit_core/managers/node_manager.py:551`).
- `node dev-link` is the current preferred local-development conversion path
  when replacing a tracked registry/git node with a symlinked checkout, because
  it preserves the existing manifest identifier
  (`packages/core/src/comfygit_core/managers/node_manager.py:666`,
  `packages/cli/comfygit_cli/cli.py:981`).
- `node remove` distinguishes untracking from filesystem deletion. Development
  nodes and explicit `--untrack` leave files alone; tracked registry/git nodes
  delete the materialized directory and clean manifest references/sources
  (`docs/specs/environment-manifest-model.md:175`,
  `packages/core/src/comfygit_core/managers/node_manager.py:935`,
  `packages/core/src/comfygit_core/managers/node_manager.py:982`).
- Node dependency groups are collision-resistant hash-based groups, not simple
  `node/<id>` groups (`packages/core/src/comfygit_core/managers/pyproject_manager.py:1725`).
- Constraints live in `[tool.uv].constraint-dependencies` as uv-style strings,
  not as a TOML table keyed by package (`packages/core/src/comfygit_core/managers/pyproject_manager.py:1283`).
- Default sync extras are stored under `tool.comfygit.sync.extras` and can be
  managed with `cg env-config extras ...`
  (`packages/core/src/comfygit_core/managers/pyproject_manager.py:483`,
  `packages/cli/comfygit_cli/cli.py:536`).
- Local source/index/package overrides should be taught through overlays,
  especially gitignored local overlays, rather than committed manifest truth
  (`docs/contracts/core/CONTRACT.md:345`,
  `packages/cli/comfygit_cli/cli.py:567`,
  `packages/cli/comfygit_cli/env_commands.py:600`).
- `comfygit-manager` self-update has special ordering: replacement metadata and
  cached contents are prepared before mutating the current manager manifest entry
  or dependency group (`docs/contracts/core/CONTRACT.md:277`,
  `packages/core/src/comfygit_core/managers/node_manager.py:1839`).

## 4. Gaps/stale/misleading content with file references

- `adding-nodes.md` still presents `cg node add <name> --dev` as the main
  development workflow (`docs/comfygit-docs/docs/user-guide/custom-nodes/adding-nodes.md:171`).
  It should explain the difference between `--dev` and `node dev-link`, and
  recommend `dev-link` when converting an already tracked registry/git node.
- The same page says a teammate can auto-clone a dev node if the directory is
  missing (`adding-nodes.md:246`) but does not explain pinned commit vs branch,
  or that local paths alone are not portable.
- The docs do not mention canonical manifest node IDs, exact local aliases, or
  consensus reuse of `custom_node_map`. This is central to workflow node
  reproducibility after the resolver work.
- No public node page explains node criticality/optional nodes, even though the
  truth layer now makes this a documented package-level behavior.
- The dependency-group examples use `node/comfyui-impact-pack` and
  `[project.optional-dependencies]` for node dependencies
  (`py-commands.md:273`, `py-commands.md:655`). Current code generates
  hash-based PEP 735 `[dependency-groups]` entries for nodes.
- The constraints docs show `[tool.uv.constraint-dependencies]` as a TOML table
  (`constraints.md:59`), but current code stores uv constraint strings under
  `[tool.uv].constraint-dependencies`.
- Several published commands appear unsupported by the current parser:
  `cg node update --check` (`dependency-conflicts.md:138`),
  `cg node update --all` (`dependency-conflicts.md:491`),
  `cg node list --verbose` (`dependency-conflicts.md:78`),
  `cg constraint add -r constraints.txt` (`dependency-conflicts.md:466`), and
  `cg node search` (`uv-errors.md:81`).
- `uv-errors.md` uses `cg sync --torch-backend cuda` (`uv-errors.md:365`), but
  current help text/examples use concrete backend IDs such as `cpu`, `cu128`,
  `cu126`, `cu124`, `rocm6.3`, and `xpu`
  (`packages/cli/comfygit_cli/cli.py:597`).
- Recovery guidance includes `cg reset --hard HEAD~1` (`uv-errors.md:500`),
  which should not be front-line public troubleshooting without strong warnings.
  It is destructive and outside the safer ComfyGit node/dependency model.
- The docs warn against installing ComfyUI-Manager, but do not clearly separate
  it from `comfygit-manager` or document `cg manager status/update`
  (`adding-nodes.md:357`, `packages/cli/comfygit_cli/cli.py:1220`).
- There is little coverage of dependency overlays and local source overrides.
  This leaves users likely to mutate venvs or committed pyproject state for
  machine-local development.
- Public docs duplicate conflict content across
  `node-conflicts.md`, `dependency-conflicts.md`, `constraints.md`, and
  `uv-errors.md`. Some duplication is useful, but the current split has
  conflicting command examples.

## 5. Proposed public-doc pages/sections and where each concept should live

- `user-guide/custom-nodes/overview.md` or revised `adding-nodes.md`
  - Registry add vs Git add vs development add.
  - What gets written to the manifest.
  - Canonical manifest ID vs registry ID vs directory name vs repository URL.
  - The short rule: use canonical IDs in workflow dependency references.

- `user-guide/custom-nodes/development-nodes.md`
  - Local development story.
  - `cg node dev-link` as the main "replace this tracked node with my checkout"
    command.
  - `cg node add <dir> --dev` as "track an existing local custom_nodes
    directory" rather than the only development flow.
  - Git provenance, branch, pinned commit, and portability.
  - What happens when removing or untracking development nodes.

- `user-guide/custom-nodes/managing-nodes.md`
  - Keep list/update/remove/prune here.
  - Add `--untrack`.
  - Explain update behavior by source type: registry, git, development,
    manager.
  - Explain sequential batch behavior and no automatic rollback of earlier
    successful batch items.

- `user-guide/custom-nodes/optional-nodes.md` or a section in managing nodes
  - Define required vs optional custom nodes.
  - Explain that only explicit user action should mark a node optional.
  - Explain partial state: local readiness/UI can honor it; build/deploy
    consumption is still evolving.

- `user-guide/python-dependencies/dependency-groups.md`
  - PEP 735 dependency groups.
  - Hash-based node groups.
  - Base dependencies from `cg py add`, dev groups, optional extras, and
    default sync extras.
  - `cg py remove --group` and `cg py remove-group`.

- `user-guide/python-dependencies/overlays-and-local-sources.md`
  - Machine-local package sources and indexes.
  - `cg overlay create --local`, `overlay enable`, `overlay show`, and when to
    use them instead of committed dependency edits.
  - Relationship to local editable sources and PyTorch backend injection.

- `user-guide/python-dependencies/constraints.md`
  - Keep as the single canonical constraints page.
  - Correct storage shape and examples.
  - Link conflict pages back here instead of duplicating long constraint
    primers.

- `troubleshooting/dependency-conflicts.md`
  - Keep symptom-first conflict triage.
  - Replace unsupported commands with current safe commands.
  - Link out to constraints, overlays/local sources, and separate-environment
    guidance.

- `user-guide/custom-nodes/manager.md` or a short subsection in managing nodes
  - Explain `comfygit-manager` as a ComfyGit-managed custom node.
  - Explain `cg manager status`, `cg manager update`, restart requirement, and
    manual ComfyUI Registry update fallback.
  - Explicitly distinguish from ComfyUI-Manager.

## 6. Safe command examples to publish

These command shapes match the current parser/code:

```bash
cg node add comfyui-impact-pack
cg node add comfyui-impact-pack@1.2.0
cg node add https://github.com/ltdrdata/ComfyUI-Impact-Pack
cg node add https://github.com/ltdrdata/ComfyUI-Impact-Pack@main
cg node add comfyui-impact-pack --strict
cg node add comfyui-impact-pack --no-test
cg node add comfyui-impact-pack --extra cuda
cg node add comfyui-impact-pack --all-extras
cg node add comfyui-impact-pack --resolve-with-overlays
cg node add node-a node-b node-c
```

```bash
cg node dev-link comfyui-impact-pack --path ~/dev/ComfyUI-Impact-Pack --replace-existing
cg node dev-link my-local-node --path ~/dev/my-local-node --name my-local-node
```

```bash
cg node list
cg node update comfyui-impact-pack
cg node update comfyui-impact-pack --yes
cg node update comfyui-impact-pack --no-test
cg node remove comfyui-impact-pack
cg node remove comfyui-impact-pack --untrack
cg node remove node-a node-b
cg node prune
cg node prune --exclude comfyui-impact-pack
cg node prune --yes
```

```bash
cg py add requests pillow
cg py add -r requirements.txt
cg py add pytest ruff --dev
cg py add sageattention --group optional-cuda
cg py add "git+https://github.com/thu-ml/SageAttention.git" --optional cuda --no-build-isolation
cg py add /path/to/my-package --editable
cg py list
cg py list --all
cg py remove requests
cg py remove sageattention --group optional-cuda
cg py remove-group optional-cuda
cg py uv lock
```

```bash
cg constraint add "numpy>=1.24,<2"
cg constraint list
cg constraint remove numpy
```

```bash
cg env-config extras add cuda
cg env-config extras show
cg env-config extras remove cuda
cg overlay create --local
cg overlay show .local
cg overlay enable .local
cg overlay disable .local
```

```bash
cg manager status
cg manager update
cg manager update --version 0.1.3 --yes
```

## 7. Open questions/risks

- Is there, or should there be, a public CLI command for setting custom-node
  criticality? Core storage exists, but I did not find a node criticality CLI
  command in `packages/cli/comfygit_cli/cli.py`. If Manager is the only current
  UI for this, public docs should say so.
- The CLI parser could not be executed with `uv run cg ... -h` in this checkout
  because the repo `.venv` points to an unreadable interpreter. Command examples
  above are validated against parser source, not runtime help output.
- Conflict docs should avoid implying that ComfyGit can always auto-fix uv
  conflicts. The current probe behavior is useful, but users still need to know
  when to use constraints, overlays, separate environments, or upstream fixes.
- Manager update docs need to account for broken older versions where self-update
  may fail and users must update through the ComfyGit panel/Nodes UI or ComfyUI
  Registry flow. The public wording should be operational, not too internal.
- The final docs should avoid encouraging manual edits to generated or
  collision-resistant dependency group names unless the user is explicitly in an
  advanced troubleshooting section.
