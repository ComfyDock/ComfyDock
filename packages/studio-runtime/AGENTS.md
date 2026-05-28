# Studio Runtime Agent Notes

This directory is the shared `comfygit-studio` Python runtime package. It owns
the contract HTTP API, embedded Manager routes, local `cg serve` routing,
Studio static asset serving, upload handling, run/gallery/session state, output
proxying, and ComfyUI execution adapters.

Core owns environment and contract domain semantics. The CLI and Manager are
hosts for this runtime; they should not duplicate the contract API, gallery
state, upload, or output-delivery behavior.

## File Layout

- `comfygit_studio/runtime.py`: main aiohttp handlers, `cg serve` app creation,
  public Studio contract API routes, proxy runtime routes, upload/run/gallery
  orchestration, and output delivery.
- `comfygit_studio/embedded.py`: helpers for registering the same Studio
  runtime inside an existing aiohttp host such as ComfyUI Manager.
- `comfygit_studio/executor.py`: local and proxy ComfyUI execution adapters.
- `comfygit_studio/state.py`: ephemeral and SQLite runtime state stores for
  sessions, runs, output slots, and gallery items.
- `comfygit_studio/api_schema.py`: source of truth for the public OpenAPI
  document.
- `comfygit_studio/openapi/studio-contract-api.v1.json`: generated OpenAPI
  artifact checked into the repo.
- `comfygit_studio/static/`: generated bundled Studio frontend assets copied
  from `packages/studio/dist/static/`.
- `tests/`: focused runtime, embedded route, OpenAPI, and state behavior tests.

## OpenAPI Workflow

The public contract API is documented by generated OpenAPI JSON. The source is
`comfygit_studio/api_schema.py`; do not hand-edit
`comfygit_studio/openapi/studio-contract-api.v1.json`.

Run this when the public contract API changes:

```bash
make generate-openapi
```

Run this during validation to ensure the generated artifact matches the source:

```bash
make check-openapi
```

Public API routes should stay aligned with `PUBLIC_STUDIO_API_ROUTES` in
`api_schema.py`. That list is used by tests to make sure the documented public
API and registered runtime routes do not drift.

The OpenAPI document is for the client-facing contract API shared by local
`cg serve`, Manager-embedded Studio, and future hosted endpoints. Keep internal
worker/proxy plumbing out of this public spec unless the truth layer is updated
to make those routes public.

## Static Studio Assets

The runtime package serves built Studio frontend assets from
`comfygit_studio/static/`. Those files are generated from `packages/studio/`.

Run this when frontend behavior changes and the runtime package needs the new
bundle:

```bash
make build-studio
```

That command builds `packages/studio` and syncs the result into
`comfygit_studio/static/`. Commit the generated static asset changes together
with the frontend source changes they came from.

## Working Rules

- Keep the public route shapes stable and documented in `api_schema.py`,
  `docs/specs/workflow-contract-serving-lifecycle.md`, and public docs when
  behavior changes.
- Prefer adding typed state/store affordances in `state.py` over having route
  handlers know SQLite or in-memory implementation details.
- Keep backward compatibility for public API response fields unless the truth
  layer explicitly changes the contract.
- Use cursor pagination for gallery listing. `GET /gallery` without `limit`
  remains backward-compatible and returns all items; paginated clients should
  use `limit` plus opaque `next_cursor`.
- Keep runtime state out of core and out of portable environment manifests.

## Validation

Useful focused checks from the repo root:

```bash
uv run pytest packages/studio-runtime/tests -q
uv run pytest packages/cli/tests/test_serve_command.py -q
uv run ruff check packages/studio-runtime/comfygit_studio packages/studio-runtime/tests dev/scripts/generate-studio-openapi.py
uv run ty check packages/studio-runtime/comfygit_studio/api_schema.py packages/studio-runtime/comfygit_studio/state.py packages/studio-runtime/comfygit_studio/runtime.py packages/studio-runtime/comfygit_studio/embedded.py
make check-openapi
make build-studio
```

Run the truth-layer validator when changing public API behavior or lifecycle
guarantees:

```bash
python3 /home/akatzfey/dev/ai-tools/akatz-skills/plugins/spec-workflows/skills/spec-driven-development/scripts/validate_contract_docs.py docs
```
