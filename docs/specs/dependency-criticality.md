# Dependency Criticality

Dependency criticality tells ComfyGit whether a missing or unreproducible
dependency should block export/import/build flows or be surfaced as a warning.

## Shared Semantics

### CGCRIT-DEP-01 [LIVE]: Required means the environment is not reproducible without it
Validation: MIXED

Required dependencies must be available through local state, registry metadata,
source URL, or content-addressed cache before a reproducible environment can be
claimed.

### CGCRIT-DEP-02 [LIVE]: Optional means absence is allowed but visible
Validation: MIXED

Optional dependencies may be absent from a target environment, but tooling should
surface that fact to the user because workflow behavior may change.

### CGCRIT-DEP-03 [LIVE]: Flexible model criticality is model-specific
Validation: MIXED

Model criticality may use the existing flexible category for assets that are not
strictly required in every run but are more important than purely optional assets.
Custom node criticality should not inherit this third state unless a concrete
need appears.

## Custom Nodes

### CGCRIT-NODE-01 [PARTIAL]: Custom nodes use required or optional criticality
Validation: MIXED

Custom node criticality should initially support only `required` and `optional`.
This keeps build-readiness behavior easy to reason about. Core manifest
read/write support and manager UI controls exist; centralized core readiness and
cloud build behavior are tracked as follow-on work.

### CGCRIT-NODE-02 [LIVE]: Missing custom node criticality reads as required
Validation: TEST

Readers should treat missing custom node criticality as required. Core writers
should emit the field explicitly for newly written node entries.

### CGCRIT-NODE-03 [LIVE]: Graph usage does not override user-declared node criticality
Validation: HUMAN_REVIEW

Workflow graph analysis may help explain why a node looks unused, but it must not
silently set, downgrade, or upgrade package-level custom node criticality.
Custom nodes can affect runtime behavior outside visible workflow node
instances, so only explicit user action may mark an installed custom node
optional.

## Readiness Outcomes

### CGCRIT-READY-01 [PARTIAL]: Required unresolved dependencies block reproducibility readiness
Validation: MIXED

Required models or custom nodes without an acquisition path should be reported as
reproducibility issues before export, push, or cloud build planning. Manager
surfaces this today for local handoff flows; the reusable core readiness service
and cloud build planner integration are still planned.

### CGCRIT-READY-02 [PARTIAL]: Optional custom node gaps are not portable build inputs
Validation: MIXED

Optional custom nodes may remain tracked in local environment state without being
required for export, push, or cloud build readiness. Detailed inspection may show
that an optional node lacks portable provenance, but top-level reproducibility
checks should not treat it as a dependency the portable build must acquire.
