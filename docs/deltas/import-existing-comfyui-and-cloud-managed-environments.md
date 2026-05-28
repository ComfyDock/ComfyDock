# Delta Dossier: Import Existing ComfyUI And Cloud-Managed Environments

## Clauses

- CGCORE-LIB-04
- CGCORE-MAN-01
- CGCORE-MAN-03
- CGCORE-MAN-04
- CGCORE-MAN-05
- CGCORE-MAN-06
- CGCORE-DEP-02
- CGCORE-DEP-02A
- CGCORE-DEP-03
- CGSPEC-MAN-01
- CGSPEC-MAN-03
- CGSPEC-MAN-04
- CGSPEC-MAN-09
- CGSPEC-NODE-01
- CGSPEC-NODE-02A
- CGSPEC-MODEL-01
- CGSPEC-MODEL-02
- CGSPEC-MODEL-04

## Motivation

ComfyGit's current power-user path assumes users are willing to learn at least
some combination of uv, CLI commands, git commits, GitHub repositories, and
remote handoff. That is reasonable for technical users, but it creates too much
friction for users who already have a working unmanaged ComfyUI installation and
mainly want to turn that working setup into a reproducible API or Studio-backed
deployment.

The future onboarding path should start from what those users already know:
"this ComfyUI install works on my machine." ComfyGit should then help them
import that install into a managed environment, show the reproducibility gaps,
let them fix those gaps through Manager or a launcher UI, and deploy a saved
version without requiring GitHub as the first concept.

## Current Evidence

- Existing truth:
  - `docs/contracts/core/CONTRACT.md`
  - `docs/specs/environment-manifest-model.md`
  - `docs/specs/environment-materialization-lifecycle.md`
  - `docs/specs/workflow-contract-serving-lifecycle.md`
- Existing implementation areas:
  - `packages/core/src/comfygit_core/core/environment.py`
  - `packages/core/src/comfygit_core/core/workspace.py`
  - `packages/core/src/comfygit_core/managers/pyproject_manager.py`
  - `packages/core/src/comfygit_core/managers/node_manager.py`
  - `packages/core/src/comfygit_core/managers/model_manager.py`
  - `packages/core/src/comfygit_core/services/environment_readiness.py`
  - `packages/cli/comfygit_cli/`
- Adjacent consumers:
  - sibling `comfygit-manager` repo for unmanaged-environment detection,
    onboarding UI, and environment switching
  - sibling `comfygit-cloud` repo for cloud-managed remotes, environment
    revisions, builds, deployments, and published endpoints

## Gap

Users who do not already know the ComfyGit workflow have a high-friction path:

- install ComfyGit or Manager
- create a workspace and managed environment
- reproduce or migrate their existing custom nodes, workflows, and model layout
- create or connect a GitHub repository
- commit and push environment state
- create a Cloud environment from that GitHub repository
- deploy a commit

This path asks users to understand the reproducibility model before they have
seen the deployment value. It also makes GitHub a mandatory onboarding step even
when ComfyGit Cloud could own the remote history internally.

There is also no first-class product flow for importing an already-running
unmanaged ComfyUI installation into a managed ComfyGit environment. Users can
manually recreate pieces of the environment, but they do not get a guided report
that separates:

- what ComfyGit can reproduce automatically
- what can be inferred but needs confirmation
- what is unknown and requires user input
- which gaps block deployment versus only warn

## Proposed Change

Add a future onboarding path centered on "Import Existing ComfyUI" and
Cloud-managed environment history.

The intended beginner flow is:

1. User opens an unmanaged ComfyUI installation with ComfyGit Manager installed,
   or opens a future ComfyGit launcher.
2. ComfyGit detects that the current ComfyUI process is not running inside a
   managed ComfyGit environment.
3. User chooses "Import Existing ComfyUI".
4. ComfyGit scans the running installation and produces a reproducibility
   report.
5. User creates a new managed environment from the report.
6. The orchestrator or launcher switches the user into the imported managed
   environment.
7. User fixes reproducibility warnings using the normal Manager controls.
8. User saves a version, backed by a git commit in the managed environment.
9. User signs into ComfyGit Cloud and deploys that version.
10. ComfyGit Cloud stores the environment history as a Cloud-managed remote,
    then builds and deploys selected commits.

The product model should support two environment backing modes:

- GitHub-backed environments for technical users who want an explicit
  repository and branch.
- Cloud-managed environments for users who want ComfyGit Cloud to own the
  remote git history internally.

Both modes should keep git commits as the durable environment revision model.
Beginner-facing UI may call these "versions" while preserving commit identity in
advanced details, logs, and handoff metadata.

## Import Responsibilities

An import scanner should attempt to identify:

- ComfyUI version, checkout source, and commit when available.
- Python version and package state.
- Installed custom nodes, including registry ids, git remotes, local paths, and
  pinned commits when available.
- Workflows and workflow contract artifacts present in the installation.
- Model files by path, category, size, content hash, and known source matches.
- Missing or ambiguous node provenance.
- Missing model sources and model files that cannot be read or hashed.
- Local-only configuration that should not become portable manifest truth.

The import result should be explicit about confidence. It should not silently
convert guesses into portable truth.

## Model Handling

Model bytes are external assets and may be very large. Import should not blindly
copy or upload every local model file.

The expected first behavior is:

- index local model files by hash and path when readable
- preserve expected model-relative paths in the managed environment
- reuse local model storage where practical for the local imported environment
- attach models to workflows only when graph analysis or explicit user action
  supports that dependency
- require a source URL, known hash match, or future private upload path before a
  Cloud deployment treats the model as reproducible

Future Cloud behavior may allow private model uploads, but that should be a
separate storage, quota, policy, and cost decision. It should not be implied by
the first import flow.

## Cloud Responsibilities

For Cloud-managed environments, ComfyGit Cloud should act like an internal git
remote owned by the service:

- receive commits from Manager, launcher, or CLI
- store environment revision metadata
- expose version history in the dashboard
- build/deploy from selected commits
- keep published endpoints stable across deployment updates
- allow later export or connection to a user-owned GitHub repository when
  desired

This preserves the ComfyGit mental model while removing GitHub from the beginner
onboarding path.

## UX Language

Power users can see "commits", branches, remotes, and git metadata directly.
Beginner-oriented surfaces should prefer:

- "Import Existing ComfyUI"
- "Managed Environment"
- "Save Version"
- "Deploy Version"
- "Reproducibility Report"
- "Fix Required Issues"

The underlying commit SHA should remain visible in advanced details, logs, build
records, and deployment provenance.

## Non-Goals

- Do not require GitHub for the beginner import-and-deploy path.
- Do not hide reproducibility gaps or imply that arbitrary ComfyUI installs can
  always be reproduced automatically.
- Do not blindly copy or upload all local model bytes during import.
- Do not treat virtualenvs, caches, generated databases, logs, or local overlays
  as portable manifest truth.
- Do not replace the power-user GitHub-backed environment flow.
- Do not make Cloud provider details such as Modal Apps, function names, or
  provider URLs part of the user-facing environment identity.

## Affected Files

Likely future implementation areas in this repo:

- `packages/core/src/comfygit_core/services/unmanaged_environment_import.py`
- `packages/core/src/comfygit_core/services/environment_readiness.py`
- `packages/core/src/comfygit_core/analyzers/model_scanner.py`
- `packages/core/src/comfygit_core/managers/node_manager.py`
- `packages/core/src/comfygit_core/managers/model_manager.py`
- `packages/core/src/comfygit_core/managers/pyproject_manager.py`
- `packages/core/src/comfygit_core/core/environment.py`
- `packages/core/src/comfygit_core/core/workspace.py`
- `packages/cli/comfygit_cli/`

Likely sibling-repo implementation areas:

- `comfygit-manager` unmanaged detection, import wizard, report UI, sign-in,
  deploy-version action, and orchestrator handoff.
- `comfygit-cloud` Cloud-managed environment remotes, dashboard version history,
  build planning, deployment records, and published endpoint routing.

## Validation

Future implementation should prove:

- importing an unmanaged ComfyUI install creates a managed environment without
  mutating the source install.
- the managed environment stores portable truth in `pyproject.toml` and tracked
  workflow artifacts rather than runtime directories.
- unreadable model files, unknown model sources, and ambiguous custom-node
  provenance appear in a reproducibility report.
- required unresolved dependencies block Cloud deployment readiness, while
  optional gaps remain warnings.
- the imported environment can be switched to and booted locally.
- a saved version is represented by a git commit.
- Cloud-managed remotes preserve commit history without requiring a GitHub repo.
- GitHub-backed and Cloud-managed environments share the same deployment
  revision model.

## Future Promotion

This dossier is intentionally directional. When implementation starts, promote
the stable pieces into binding specs and contracts:

- import lifecycle semantics in `docs/specs/`
- core readiness/import guarantees in `docs/contracts/core/CONTRACT.md`
- Cloud-managed remote and deployment guarantees in the Cloud repo truth layer
- Manager onboarding UI guarantees in the Manager repo truth layer
