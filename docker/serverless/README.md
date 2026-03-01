# ComfyGit Serverless

Deploy any ComfyGit environment as a serverless GPU endpoint on RunPod.

## Architecture

```
Docker Image (small, ~4.5GB)         Network Volume (persistent, ~25GB)
┌─────────────────────────┐         ┌──────────────────────────────────┐
│ - CUDA 12.6 runtime     │         │ /runpod-volume/                  │
│ - Python 3.12           │         │ ├── comfygit-workspace/          │
│ - ComfyGit CLI          │         │ │   └── environments/            │
│ - RunPod handler        │  ────▶  │ │       ├── blue/  (active)      │
│                         │  reads  │ │       └── green/ (standby)     │
│ No models baked in!     │         │ ├── models/  (shared)            │
│ No ComfyUI baked in!    │         │ └── .state.json                  │
└─────────────────────────┘         └──────────────────────────────────┘
```

The Docker image is intentionally small — it contains only the orchestration layer.
Models, ComfyUI, custom nodes, and Python environments all live on the RunPod
network volume and persist across worker restarts and scale-to-zero events.

## A/B Deployment Pattern

Two environments (blue/green) live on the network volume:

- **Active** environment serves inference requests
- **Standby** environment receives updates via `cg pull`
- On successful update, the active pointer swaps to the updated environment
- On failure, the previous environment remains untouched

## Quick Start

### Build

```bash
cd docker/serverless
docker build -t comfygit-serverless .
```

### Test Locally

```bash
# Simulate RunPod network volume with a local directory
mkdir -p /tmp/runpod-volume

# Run with GPU (requires nvidia-container-toolkit)
docker run --gpus all \
  -v /tmp/runpod-volume:/runpod-volume \
  -e COMFYGIT_REPO=https://github.com/Akatz-Workflows/Z-Image-Simple.git \
  -e COMFYGIT_REPO_REF=615a29b \
  -e SERVE_API_LOCALLY=true \
  -p 8000:8000 \
  comfygit-serverless

# Test inference
curl -X POST http://localhost:8000/runsync \
  -H "Content-Type: application/json" \
  -d '{"input": {"workflow_name": "z-image", "prompt": "a cat in space"}}'
```

### Test Without Docker

```bash
# Test A/B manager logic (no GPU needed)
python test_local.py --test-ab-manager

# Test handler against a running ComfyUI instance
python test_local.py --comfyui-running
```

### Deploy to RunPod

1. Push image to GHCR: `docker push ghcr.io/comfygit-ai/comfygit-serverless:latest`
2. Create a 25GB network volume on RunPod
3. Create a serverless endpoint with the image + network volume attached
4. First request triggers environment setup (~5 min for model download)
5. Subsequent cold starts: ~30-60s. Warm requests: instant.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMFYGIT_REPO` | Yes | — | Git URL of the ComfyGit environment |
| `COMFYGIT_REPO_REF` | No | `main` | Git ref (commit, branch, tag) to deploy |
| `COMFYGIT_LOWVRAM` | No | `true` | Use `--lowvram` flag for ComfyUI |
| `COMFYGIT_VOLUME_PATH` | No | `/runpod-volume` | Path to persistent storage |
| `COMFYGIT_ACTIVE_ENV` | No | `blue` | Initial active environment name |
| `SERVE_API_LOCALLY` | No | `false` | Start local API server for testing |

## API Reference

### Inference Request

```json
{
  "input": {
    "workflow_name": "z-image",
    "prompt": "a majestic cat in space",
    "seed": 42,
    "steps": 12,
    "width": 1024,
    "height": 1024,
    "return_base64": true
  }
}
```

### Response

```json
{
  "outputs": [
    {
      "type": "image",
      "filename": "ComfyUI_00001_.png",
      "data": "<base64-encoded-png>"
    }
  ],
  "prompt_id": "abc-123",
  "execution_time": 10.5
}
```

### Management Commands

```json
{"input": {"command": "status"}}
{"input": {"command": "update"}}
```

### Advanced: Raw Workflow

Pass a full ComfyUI API-format workflow for complete control:

```json
{
  "input": {
    "workflow": {
      "1": {"class_type": "UNETLoader", "inputs": {...}},
      ...
    }
  }
}
```

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Container image build recipe |
| `handler.py` | RunPod serverless handler + built-in workflow builders |
| `ab_manager.py` | Blue/green environment manager |
| `start.sh` | Container entrypoint script |
| `test_local.py` | Local test harness |
| `test_input.json` | Sample RunPod test payload |

## Related

- [`packages/deploy`](../../packages/deploy/) — `cg-deploy` CLI for managing RunPod pods and instances
- [`docker/base`](../base/) — Base Docker image for ComfyGit environments
