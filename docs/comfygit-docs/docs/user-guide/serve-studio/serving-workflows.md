# Serve Workflows With Studio

`cg serve` hosts a small Studio UI and contract-shaped HTTP endpoints for a
ComfyGit environment.

Use it when you want to run a saved workflow through a focused UI or API instead
of exposing the full ComfyUI graph editor.

## What Serve Does

`cg serve`:

- Reads workflow contracts from the active environment.
- Hosts the packaged ComfyGit Studio at `/`.
- Exposes contract metadata and run endpoints.
- Uploads media inputs through file refs.
- Sends prepared prompts to a running ComfyUI API.
- Maps ComfyUI history outputs back to contract outputs.

`cg serve` does not launch ComfyUI. Start ComfyUI first.

## Prerequisites

You need:

- A runnable ComfyGit environment.
- A workflow tracked in the environment.
- A workflow contract saved through ComfyGit Manager.
- ComfyUI running and reachable by URL.

## Start ComfyUI

In one terminal:

```bash
cg run -- --listen 127.0.0.1 --port 8188
```

## Start Serve

In another terminal:

```bash
cg serve \
  --host 127.0.0.1 \
  --port 8190 \
  --comfy-url http://127.0.0.1:8188
```

Open:

```text
http://127.0.0.1:8190
```


## Run From HTTP

List available contracts:

```bash
curl http://127.0.0.1:8190/contracts
```

Run a contract:

```bash
curl -X POST \
  http://127.0.0.1:8190/contracts/my-workflow/default/run \
  -H 'content-type: application/json' \
  -d '{
    "inputs": {
      "prompt": "a cinematic portrait"
    },
    "wait": true
  }'
```

The exact input names come from the saved contract.

## Runtime State

By default, serve state is ephemeral. It exists only while the process is
running.

Use local SQLite state when you want runs and gallery rows to survive restarts:

```bash
cg serve --state local --gallery private
```

Use a shared gallery when multiple clients should see the same output history:

```bash
cg serve --state local --gallery shared
```

Serve state is runtime adapter state. It is not portable environment truth and
should not be confused with the manifest.

## Local And Proxy Execution

The default executor sends prompts to the local ComfyUI URL:

```bash
cg serve --executor local --comfy-url http://127.0.0.1:8188
```

Proxy mode lets a Studio/front-door serve process send work to another
compute-only serve runtime:

```bash
cg serve \
  --executor proxy \
  --proxy-url http://runtime.internal:8191 \
  --proxy-token "$COMFYGIT_PROXY_TOKEN"
```

The proxy runtime uses:

```bash
cg serve \
  --role proxy \
  --host 0.0.0.0 \
  --port 8191 \
  --comfy-url http://127.0.0.1:8188 \
  --proxy-token "$COMFYGIT_PROXY_TOKEN"
```

Most local users should start with the default local executor.

## Related Guides

- [Workflow contracts](../workflows/workflow-contracts.md)
- [Uploads and file refs](uploads.md)
- [Materialize runtime environments](../collaboration/materialize.md)
