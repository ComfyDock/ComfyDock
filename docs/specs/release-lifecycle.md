# Release Lifecycle

This spec describes release-time invariants for the ComfyGit monorepo. It covers
the release artifacts in this repository and the ordering constraints that matter
to adjacent packages such as ComfyGit Manager.

## Lockstep Artifacts

### CGREL-LOCK-01 [LIVE]: Core, CLI, and bundled Studio use lockstep release versions
Validation: STATIC

Every ComfyGit monorepo release uses one version for `comfygit-core`,
`comfygit`, and `@comfygit/studio`. The CLI package must pin
`comfygit-core==<same version>`, and release checks must fail when these versions
diverge.

### CGREL-STUDIO-01 [LIVE]: CLI releases include the built Studio static bundle
Validation: STATIC

The Studio source package is not a runtime dependency of the installed CLI.
Before building or publishing the CLI release artifact, release tooling must
build `packages/studio`, sync the emitted static assets into
`packages/cli/comfygit_cli/studio_static`, and package those assets with the CLI
wheel so `cg serve` can host Studio without Node.js.

### CGREL-PUB-01 [LIVE]: Core is published before the CLI
Validation: STATIC

Because the CLI pins `comfygit-core==<release version>`, the release workflow
must publish `comfygit-core` first and wait until that version is visible on
PyPI before building and publishing `comfygit`.

## Adjacent Releases

### CGREL-MGR-01 [PARTIAL]: Manager releases depend on published core versions
Validation: HUMAN_REVIEW

The ComfyGit Manager release is owned by the sibling manager repository, but it
must not pin or publish against a `comfygit-core` version that is unavailable on
PyPI. Manager release preparation should happen after the corresponding core
release is published and visible.

This remains partial until cross-repository automation enforces the ordering.

## Retired Artifacts

### CGREL-DEPLOY-01 [LIVE]: `comfygit-deploy` is retired from this monorepo release surface
Validation: STATIC

`packages/deploy` and `comfygit-deploy` are not release artifacts in this
monorepo. Release tooling, version checks, build targets, tests, workspace
members, and publish workflows must not treat deploy as an active package.
Local/manual serving belongs to `cg serve`; hosted provider deployment belongs
to ComfyGit Cloud or external adapters.

### CGREL-WF-01 [PARTIAL]: Release process docs should match the active publish workflow
Validation: STATIC

Repository release docs and agent instructions should describe the active
workflow names, package names, release artifact order, and required validation.
Stale release docs that point at removed workflows or old package names are
maintenance gaps because they can cause incorrect release execution.
