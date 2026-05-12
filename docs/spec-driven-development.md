# Spec-Driven Development

ComfyGit uses a small root truth layer to keep implementation work aligned with
the behavior the project intends to maintain. The truth layer is separate from
public user documentation and from historical task records.

## Truth Layer Order

When deciding what the system is supposed to do, prefer sources in this order:

1. `docs/contracts/` - normative guarantees, boundaries, and invariants.
2. `docs/specs/` - lifecycle behavior, state transitions, and data semantics.
3. `packages/*/docs/` - package architecture, design notes, and reference.
4. `docs/comfygit-docs/` - public-facing user documentation.

If two active truth-layer documents conflict, update the truth layer before
changing implementation. Public docs should follow the truth layer, not define it.

## Clause Format

Normative clauses use stable headings:

```md
### CGCORE-MAN-01 [LIVE]: Environment manifests are the portable source of truth
Validation: TEST
```

Allowed statuses:

- `[LIVE]` - currently true and should be preserved.
- `[PARTIAL]` - partly true; implementation or tests still have known gaps.
- `[PLANNED]` - intended direction, not yet implemented.
- `[DEFERRED]` - accepted but out of current scope.
- `[RETIRED]` - no longer desired behavior.

Validation classes:

- `TEST` - executable behavioral tests should verify the clause.
- `STATIC` - lint, typing, schema checks, or static inspection are enough.
- `LLM_REVIEW` - structured code/doc review is the main evidence.
- `HUMAN_REVIEW` - product or architecture judgment is required.
- `MIXED` - more than one evidence type is expected.

## Working Rules

- Add or update clauses before implementing meaningful behavior changes.
- Mark clauses `[PARTIAL]` when they describe the intended shape but code is not
  fully aligned yet.
- Keep the truth layer smaller than the codebase. Do not turn every helper or
  implementation detail into a clause.
- Reference clause IDs in substantial commits, tests, or implementation notes
  when practical.
- Treat retired task-system state as local-only context unless the user
  explicitly asks for task-tracker migration or cleanup.

## Validation

After editing truth-layer docs, run:

```bash
python3 <path-to-spec-workflows-skill>/scripts/validate_contract_docs.py docs
```

The validator checks clause heading/status syntax. It does not decide whether a
clause is accurate; that still requires code review and tests.
