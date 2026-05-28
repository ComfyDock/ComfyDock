# Studio And Serve

`cg run` launches ComfyUI. `cg serve` does something different: it fronts an
already running ComfyUI server with contract-shaped endpoints and the packaged
ComfyGit Studio UI.

Studio is a browser UI over saved workflow contracts. It uses the same contract
API that scripts and external clients can call.

## Runtime Shape

A typical local flow is:

```bash
cg run
cg serve --port 8190 --comfy-url http://127.0.0.1:8188
```

ComfyUI remains the execution backend. `cg serve` owns the Studio UI, upload
references, contract-shaped request parsing, run records, and response shape.

## Authoring Vs Serving

Manager is the supported authoring path for workflow contracts because it can
inspect the live ComfyUI graph and capture the API prompt artifact.

`cg serve` can run existing contracts from committed environment state. It is
not the primary authoring tool for new contracts.

Read more: [Serving workflows](../user-guide/serve-studio/serving-workflows.md)
and [uploads and file refs](../user-guide/serve-studio/uploads.md).
