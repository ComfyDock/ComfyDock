# Environment Sync Lifecycle

This spec describes how ComfyGit turns an environment manifest into a runnable
local ComfyUI environment.

## Lifecycle

### CGSYNC-LIFE-01 [LIVE]: Create initializes tracked and derived state
Validation: TEST

Creating an environment should initialize the tracked manifest repository and the
derived `.cec` runtime state needed for sync/run.

### CGSYNC-LIFE-02 [LIVE]: Sync may recreate the virtual environment
Validation: TEST

Sync is allowed to recreate or replace the managed virtual environment. Users
should not rely on manually installed packages surviving unless they are captured
in manifest dependencies or local injection configuration.

### CGSYNC-LIFE-03 [LIVE]: Run syncs unless explicitly bypassed
Validation: TEST

Normal run behavior should make the environment runnable from declared state
before launching ComfyUI. Explicit no-sync flows are advanced escape hatches and
should not redefine the main lifecycle.

### CGSYNC-LIFE-04 [PARTIAL]: Repair restores derived state from truth
Validation: MIXED

Repair should use the manifest, lockfile, and local configuration to restore
missing or damaged derived runtime state. Gaps should be tracked as implementation
work, not treated as new truth.

## Git And Remote Flows

### CGSYNC-GIT-01 [LIVE]: Commit records environment truth changes
Validation: TEST

Committing should capture meaningful manifest, workflow, contract, and metadata
changes in the environment repository.

### CGSYNC-GIT-02 [PARTIAL]: Push-readiness should report reproducibility blockers
Validation: MIXED

Before pushing an environment intended for cloud consumption, ComfyGit should be
able to report obvious blockers such as required models without sources or
required node packages without portable acquisition metadata.

### CGSYNC-GIT-03 [LIVE]: Pull/checkout should be followed by reconciliation
Validation: TEST

When git operations change tracked environment state, sync/repair should reconcile
the derived runtime so the local environment matches the checked-out commit.

## Cloud Compatibility

### CGSYNC-CLOUD-01 [PLANNED]: Build readiness uses the same manifest semantics as local sync
Validation: MIXED

Cloud build planning should read the same manifest fields core writes locally.
If cloud needs a field for reproducibility, core/manager should make that field
first-class rather than relying on cloud-specific heuristics.

### CGSYNC-CLOUD-02 [PLANNED]: Source metadata should be inspectable before push
Validation: MIXED

Users should be able to see and fix missing required model/node source metadata
before pushing a commit that cloud cannot build.
