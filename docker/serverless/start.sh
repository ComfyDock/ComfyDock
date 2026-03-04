#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "ComfyGit Serverless Worker"
echo "============================================================"
echo "  Repo:   ${COMFYGIT_REPO:-<not set>}"
echo "  Ref:    ${COMFYGIT_REPO_REF:-main}"
echo "  Volume: ${COMFYGIT_VOLUME_PATH:-/runpod-volume}"
echo "  Low VRAM: ${COMFYGIT_LOWVRAM:-true}"
echo "============================================================"

# Use libtcmalloc for better memory management (if available)
TCMALLOC="$(ldconfig -p 2>/dev/null | grep -Po 'libtcmalloc.so.\d' | head -n 1 || true)"
if [ -n "${TCMALLOC}" ]; then
    export LD_PRELOAD="${TCMALLOC}"
    echo "Using tcmalloc: ${TCMALLOC}"
fi

# Configure git authentication if GITHUB_TOKEN is set
if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo "Configuring git authentication..."
    git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
    echo "  Git auth configured for github.com"
fi

# Validate required env vars
if [ -z "${COMFYGIT_REPO:-}" ]; then
    echo "ERROR: COMFYGIT_REPO environment variable is required"
    echo "  Set it to the Git URL of your ComfyGit environment"
    echo "  Example: https://github.com/Akatz-Workflows/Z-Image-Simple.git"
    exit 1
fi

# Ensure volume is accessible
VOLUME="${COMFYGIT_VOLUME_PATH:-/runpod-volume}"
if [ ! -d "${VOLUME}" ]; then
    echo "WARNING: Volume path ${VOLUME} does not exist — creating it"
    mkdir -p "${VOLUME}"
fi

# Redirect HuggingFace / pip / uv caches to the network volume.
# Without this, model downloads use /root/.cache on the container's
# ephemeral disk (~10-20GB) and fill it before the final file lands
# on the volume.
export HF_HOME="${VOLUME}/.cache/huggingface"
export HF_HUB_DISABLE_SYMLINKS_CACHE=1
export UV_CACHE_DIR="${VOLUME}/.cache/uv"
export PIP_CACHE_DIR="${VOLUME}/.cache/pip"
mkdir -p "${HF_HOME}" "${UV_CACHE_DIR}" "${PIP_CACHE_DIR}"
echo "  Caches redirected to ${VOLUME}/.cache/"

# Check if we're in local test mode (SERVE_API_LOCALLY)
if [ "${SERVE_API_LOCALLY:-false}" == "true" ]; then
    echo "Starting in local API server mode..."
    python -u /app/handler.py --rp_serve_api --rp_api_host=0.0.0.0
else
    echo "Starting RunPod handler..."
    python -u /app/handler.py
fi
