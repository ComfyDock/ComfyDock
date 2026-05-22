# Models

Model files are external assets. ComfyGit tracks metadata about them, not the
bytes themselves.

The local model index answers:

- which model files exist on this machine
- where they are under the models directory
- what category they appear to belong to
- what their hashes are
- which source hints are known

The environment manifest answers a different question: which models does this
environment or workflow need to be reproducible?

## Model Index Vs Workflow Dependency

A model can exist in the local model index without being required by any
workflow. That means ComfyGit can see the file, but it does not yet know that a
specific workflow depends on it.

When a workflow needs a model that ComfyGit cannot infer from the graph, attach
the indexed model to that workflow manually. That declares that the workflow
needs the file at the recorded relative model path.

For handoff, required models should also have source information. Without a
source, another machine may know what is missing but not where to get it.

Read more: [Model index](../user-guide/models/model-index.md) and
[workflow model dependencies](../user-guide/workflows/model-dependencies.md).
