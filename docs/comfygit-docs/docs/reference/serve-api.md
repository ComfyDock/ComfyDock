# Serve API Reference

`cg serve` hosts Studio and contract-shaped HTTP endpoints for a ComfyGit
environment. It fronts an already running ComfyUI server or a configured proxy
executor.

Start ComfyUI first:

```bash
cg run
```

Then start the serve front door:

```bash
cg serve --port 8190 --comfy-url http://127.0.0.1:8188
```

## Studio And Health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Studio UI |
| `GET` | `/health` | Serve and backend health |

## Contracts

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/contracts` | List available workflow contracts |
| `GET` | `/contracts/{workflow}/{contract}` | Show one contract |
| `POST` | `/contracts/{workflow}/{contract}/run` | Start a contract run |

Run requests use the public input names defined by the workflow contract. File
inputs should use upload references rather than inline file bytes.

## Uploads

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/uploads/prepare` | Create an upload slot |
| `PUT` | `/uploads/{upload_id}` | Upload file bytes to the slot |
| `GET` | `/uploads/{upload_id}/status` | Check upload status and receive `file_ref` |

Use the returned `file_ref` in contract run requests.

## Runs And Outputs

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/runs` | List serve run records |
| `GET` | `/runs/{run_id}` | Inspect one run |
| `POST` | `/runs/{run_id}/cancel` | Cancel a run |
| `GET` | `/outputs/view` | Fetch a serve output artifact |

## Gallery

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/gallery` | List gallery items for the current serve state |
| `DELETE` | `/gallery/{item_id}` | Delete a gallery item |

## Proxy Runtime Endpoints

When `cg serve --role proxy` is used, the proxy runtime exposes compute-facing
routes under `/proxy`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/proxy/health` | Proxy runtime health |
| `POST` | `/proxy/runs` | Start a proxy run |
| `GET` | `/proxy/runs/{prompt_id}` | Inspect a proxy run |
| `POST` | `/proxy/runs/{prompt_id}/cancel` | Cancel a proxy run |
| `GET` | `/proxy/artifacts/{artifact_id}` | Fetch a proxy artifact |

The proxy routes are runtime plumbing. Most local users interact with Studio or
the front-door contract endpoints instead.

## Related Pages

- [Serving workflows](../user-guide/serve-studio/serving-workflows.md)
- [Uploads and file refs](../user-guide/serve-studio/uploads.md)
- [Workflow contract reference](workflow-contracts.md)
