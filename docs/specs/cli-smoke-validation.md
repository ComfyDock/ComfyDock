# CLI Smoke Validation

This spec describes the repeatable CLI smoke validation suite used to catch
behavior regressions after refactors. Unit tests remain the primary guardrail for
small functions, but the smoke suite validates that real `cg` commands still
compose into the user journeys ComfyGit promises.

## Validation Shape

### CGSMOKE-CLI-01 [LIVE]: CLI smoke tests use isolated workspaces
Validation: TEST

Automated CLI smoke tests should create or copy isolated ComfyGit workspaces
instead of mutating the user's real workspace or a shared developer fixture. A
smoke run may use shared package and registry caches for speed, but workspace
state, environment repositories, model directories, remotes, exports, and
runtime files must be test-local and disposable.

The test harness should preserve a command transcript when a journey fails so
the broken command, exit code, stdout, stderr, and relevant paths are visible
without rerunning the whole sequence manually.

### CGSMOKE-CLI-02 [LIVE]: The fast journey covers local environment authoring
Validation: TEST

The fast smoke journey should run without launching ComfyUI and without
requiring registry/network access. It should exercise the main local authoring
and collaboration path through public CLI commands:

- workspace initialization and configuration display
- model directory selection, model index sync, model lookup, and stale-location
  cleanup after switching model directories
- environment creation, active-environment selection, sync, status, repair,
  manifest display, and doctor checks
- local torch backend configuration and default optional extras
- Python dependency group list/remove flows, with dependency-add coverage kept
  in focused package tests until a lightweight resolver-safe E2E path is
  available
- workflow discovery/resolution against a real saved ComfyUI workflow file
- manual workflow model dependency add/list/source/remove flows using indexed
  local model files
- environment git history, branch switching, remotes, push, pull preview,
  export, and import

Assertions should verify both command success and durable state such as manifest
contents, indexed model behavior, git state, exported files, and imported
environment paths. Output-only assertions are allowed for user-facing command
contracts, but they should not be the only evidence for stateful behavior.

### CGSMOKE-CLI-03 [LIVE]: Registry node lifecycle is a separate network lane
Validation: TEST

Registry-backed custom node smoke tests should be marked separately from the
fast local journey. They may use a shared registry cache, but they should still
operate in an isolated environment and verify:

- registry cache availability or refresh
- adding at least one representative lightweight registry node in the default
  network lane
- manifest node entries
- installed custom node directories
- dependency group sync
- `cg node list` visibility
- node removal cleanup from manifest and filesystem

This lane may be skipped when registry data is unavailable or network access is
disabled, but it should run before releases that change node install, sync,
manifest, or registry behavior.

Heavyweight registry nodes with expensive dependency resolution may be covered
by a separate slow registry lane. That lane should be easy to opt into before
node-resolution releases, but it should not make the default registry smoke
path unpredictable or routinely five-plus minutes.

### CGSMOKE-CLI-04 [LIVE]: Runtime launch smoke is a separate slow lane
Validation: TEST

Live runtime smoke tests should be marked as slow. They should start ComfyUI
through `cg run` on a dynamically selected local port, wait for a concrete
startup signal or health endpoint, then terminate the process group cleanly.

When the environment torch backend is `cpu`, the run smoke must verify that the
ComfyUI launch receives the explicit `--cpu` flag. Runtime smoke may also verify
that recently installed custom nodes import without `IMPORT FAILED`, but that
registry-dependent variant belongs to the registry/slow lane rather than the
fast local journey.

### CGSMOKE-CLI-05 [PLANNED]: Container smoke reuses the same journey
Validation: TEST

Future Docker/Podman smoke tests should reuse the same CLI journey semantics
inside a containerized runtime. Container smoke should add evidence for bind
mount identity, workspace/cache mounts, GPU/device flags, and permission
behavior without redefining which ComfyGit commands constitute the smoke
journey.

## Non-Goals

### CGSMOKE-NONGOAL-01 [LIVE]: Smoke tests are not exhaustive unit coverage
Validation: HUMAN_REVIEW

The CLI smoke suite should cover representative end-to-end journeys, not every
argument permutation. Exhaustive parsing, formatting, branch-specific error
messages, and small edge cases belong in focused package tests. The smoke suite
should stay compact enough that developers can run it deliberately after
refactors and trust failures as meaningful user-flow regressions.
