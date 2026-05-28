# ComfyGit Overview

ComfyGit turns a working ComfyUI setup into a reproducible environment you can
inspect, commit, share, repair, and run again.

It records the pieces that make a workflow runnable: custom nodes, Python
packages, model metadata, workflow files, runtime settings, and optional
workflow contracts for Studio or API serving.


## Start Here

If you are new to ComfyGit, start with the quickstart. The whole first run looks
like this:

```bash
uv tool install comfygit --upgrade
cg init
cg create demo --use
cg run
```

The full quickstart explains each step, including the Manager panel, model
indexing, workflow tracking, and the first environment commit.

[Continue with the quickstart](quickstart.md){ .md-button .md-button--primary }

## What ComfyGit Tracks

ComfyGit separates the portable recipe from local runtime state.

| Portable and committed | Local and recreated |
| --- | --- |
| Environment manifest | Python virtualenv |
| Workflow JSON files | ComfyUI checkout |
| Custom node metadata | Installed node directories |
| Python dependency metadata | Model file symlinks |
| Model metadata and source proof | Caches and logs |
| Workflow contract artifacts | Local overlays and hardware settings |
| Git history | Selected PyTorch backend |

This split lets ComfyGit answer the questions that matter when a workflow needs
to survive beyond one machine:

- What changed since the last working commit?
- Which custom nodes and Python packages does the environment need?
- Which models are required, optional, or missing a source?
- Can another machine recreate the environment?
- Can a saved workflow become a small Studio or HTTP API?

## Choose Your Path

<div class="grid cards" markdown>

- :material-play-circle-outline: **Run ComfyUI safely**

    Create an isolated ComfyUI environment, sync dependencies, and run without
    mutating a global install.

    [Create and run environments](../user-guide/environments/creating-environments.md)

- :material-share-variant-outline: **Share a workflow**

    Track workflow files, resolve node and model dependencies, add model
    sources, then commit and push or export the result.

    [Track workflow dependencies](../user-guide/workflows/workflow-resolution.md)

- :material-cube-outline: **Declare a missing model**

    Attach an already-indexed local model to a workflow when ComfyGit cannot
    infer it from the graph.

    [Declare workflow model dependencies](../user-guide/workflows/model-dependencies.md)

- :material-application-brackets-outline: **Serve a Studio or API**

    Save a workflow contract in Manager, then use `cg serve` to host the
    packaged Studio and contract-shaped endpoints.

    [Serve workflows with Studio](../user-guide/serve-studio/serving-workflows.md)

- :material-package-down: **Hydrate a headless runtime**

    Materialize a committed environment in Docker, CI, a remote machine, or a
    runtime container without opening ComfyUI.

    [Materialize runtime environments](../user-guide/collaboration/materialize.md)

</div>

## Learn The Model

Read [what ComfyGit manages](../concepts/what-comfygit-manages.md) next if you
want the mental model before running commands. Jump to
[common workflows](../user-guide/common-workflows.md) if you already know what
you want to do.
