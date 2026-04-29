# Workflow Contract Serving Lifecycle

This spec describes the intended path from a tracked ComfyGit workflow contract
to a runtime API that can execute the workflow through ComfyUI. It captures the
shared semantics that should be implemented in core before a dedicated
`cg serve` runtime or deployment layer depends on them.

## Core Execution Semantics

### CGSERVE-CORE-01 [PARTIAL]: Contracts are already tracked environment truth
Validation: TEST

Workflow execution contracts are stored in the environment manifest under the
named workflow entry. They are part of the committed environment state and should
travel with the workflow JSON when an environment is exported, pushed, or built.

Core currently persists and reads workflow execution contracts. Runtime execution
services for those contracts are still planned.

### CGSERVE-CORE-02 [PLANNED]: Core converts workflow contracts into API prompts
Validation: TEST

Core should expose a service that accepts workflow JSON, a workflow execution
contract, user-provided contract inputs, and ComfyUI `object_info`, then returns
a ComfyUI API prompt plus structured information about applied and missing
inputs. The service should handle UI-format workflow conversion, widget-name
resolution, basic type coercion, default input application, and prompt patching.

The UI-format workflow JSON remains the committed source artifact. The API prompt
is a just-in-time runtime artifact because ComfyUI's `/prompt` endpoint expects
API-format nodes keyed by node ID with `class_type` and `inputs`, while the saved
workflow contains UI/editor data such as nodes, links, groups, and viewport
state. Persisting both formats by default would create duplicate workflow truth
and force manager/CLI save paths to generate extra files.

### CGSERVE-CORE-02A [PLANNED]: Server-side conversion should be deterministic
Validation: TEST

Core should implement the UI-workflow-to-API-prompt conversion as deterministic
library behavior that can run without a browser, Manager custom node, or ComfyUI
frontend process. Tests should compare supported workflows against API prompts
exported by ComfyUI's frontend conversion where practical, so ComfyGit can track
the supported conversion surface explicitly.

### CGSERVE-CORE-03 [PLANNED]: Core extracts declared outputs from ComfyUI history
Validation: TEST

Core should expose a service that accepts a workflow execution contract and a
ComfyUI history entry, then returns the declared output metadata for the
contract. Output extraction should be based on contract output bindings rather
than ad hoc endpoint-specific assumptions.

### CGSERVE-CORE-04 [PLANNED]: Core validates contract bindings before execution
Validation: MIXED

Core should be able to report contract execution issues such as missing required
inputs, invalid node IDs, invalid widget indexes, outputs pointing to unavailable
history data, or workflow/object-info mismatches before or during execution.
Callers should receive typed errors or result objects instead of scraping string
messages.

## Runtime Adapter Boundary

### CGSERVE-RUN-01 [PLANNED]: `cg serve` fronts ComfyUI with contract-shaped endpoints
Validation: MIXED

A serve runtime should expose HTTP endpoints shaped around ComfyGit workflow
contracts while communicating with a local ComfyUI server through ComfyUI's
normal API. External callers should send contract inputs to ComfyGit; ComfyGit
should translate those inputs into a ComfyUI prompt and map the resulting
artifacts back to contract outputs.

### CGSERVE-RUN-02 [PLANNED]: Serve can run without the Manager custom node
Validation: MIXED

Contract serving must not require the ComfyGit Manager node to be installed in
the environment. Manager may author and test contracts, but serve should operate
from core manifest/workflow state so CLI-created environments remain deployable.

### CGSERVE-RUN-03 [PLANNED]: Serve owns transport and lifecycle concerns
Validation: MIXED

The serve runtime may own HTTP routing, async run records, ComfyUI request
submission, history polling, progress streams, websocket/progress proxying,
artifact retrieval, cancellation, and output delivery adapters. These concerns
should stay outside core while still using core for contract interpretation.

### CGSERVE-RUN-04 [PLANNED]: Deployed containers should expose serve, not raw ComfyUI
Validation: HUMAN_REVIEW

For production-style deployments, the externally exposed API should be the
ComfyGit serve endpoint. ComfyUI may run locally inside the same container or
runtime, but callers should not need direct access to the ComfyUI UI/API to
execute a declared contract.

## Output Delivery

### CGSERVE-OUT-01 [PLANNED]: Local output refs are the first output delivery mode
Validation: TEST

The first serve implementation may return structured local ComfyUI output
references and metadata. This is enough for local Docker and development
validation without introducing external storage policy too early.

### CGSERVE-OUT-02 [DEFERRED]: Object storage delivery is an adapter concern
Validation: MIXED

S3/R2/provider bucket uploads, signed URLs, retention policy, and large artifact
delivery should be handled by serve/deployment adapters. Core may define output
metadata types, but it should not depend on a specific storage provider.
