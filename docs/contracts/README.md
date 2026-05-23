# Contracts

Contracts are the highest-precedence ComfyGit truth layer. They describe the
behavioral guarantees and ownership boundaries that implementation work should
preserve.

Start with the smallest surface that matters:

- `core/CONTRACT.md` - core library, manifest, sync, dependency, and portability
  guarantees.

Package architecture docs and public documentation may expand on these contracts,
but they should not contradict them.

## Coverage Map

The current root truth layer intentionally covers stable behavior surfaces
rather than every helper function:

- Core library boundaries and portability guarantees:
  `docs/contracts/core/CONTRACT.md`.
- Manifest shape, custom-node identity, model metadata, local configuration,
  and release artifact semantics: `docs/specs/environment-manifest-model.md`
  and `docs/specs/release-lifecycle.md`.
- Create/sync/import/repair/git/run lifecycle behavior:
  `docs/specs/environment-sync-lifecycle.md`.
- Headless hydration behavior: `docs/specs/environment-materialization-lifecycle.md`.
- Repeatable CLI end-to-end validation:
  `docs/specs/cli-smoke-validation.md`.
- Workflow contract serving, Studio hosting, local/proxy execution, uploads,
  run state, and artifact delivery:
  `docs/specs/workflow-contract-serving-lifecycle.md`.
- Required/optional dependency semantics:
  `docs/specs/dependency-criticality.md`.

Package architecture docs may describe module layout and implementation
rationale, but behavioral promises should be promoted into the files above when
they become refactor-sensitive.
