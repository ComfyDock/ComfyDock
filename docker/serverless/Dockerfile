# ComfyGit Serverless — RunPod Worker Image
# 
# This image is intentionally small. Models and ComfyUI environments
# live on the RunPod network volume, not baked into the image.
#
# Build:
#   docker build -t comfygit-serverless .
#
# Run locally:
#   docker run --gpus all -v /tmp/runpod-volume:/runpod-volume \
#     -e COMFYGIT_REPO=https://github.com/Akatz-Workflows/Z-Image-Simple.git \
#     comfygit-serverless

ARG BASE_IMAGE=nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04
FROM ${BASE_IMAGE}

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_PREFER_BINARY=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    git \
    git-lfs \
    wget \
    curl \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && apt-get autoremove -y && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager — used by ComfyGit)
RUN wget -qO- https://astral.sh/uv/install.sh | sh \
    && ln -sf /root/.local/bin/uv /usr/local/bin/uv \
    && ln -sf /root/.local/bin/uvx /usr/local/bin/uvx

# Create a venv for the handler and ComfyGit CLI
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV VIRTUAL_ENV="/opt/venv"

# Install ComfyGit CLI + RunPod SDK + handler dependencies
RUN uv pip install \
    comfygit>=0.3.22 \
    runpod>=1.7.0 \
    requests \
    websocket-client \
    aiohttp

# Copy handler and startup files
WORKDIR /app
COPY handler.py .
COPY start.sh .
COPY ab_manager.py .
COPY test_input.json .
RUN chmod +x start.sh

# Default environment variables
ENV COMFYGIT_REPO=""
ENV COMFYGIT_REPO_REF="main"
ENV COMFYGIT_LOWVRAM="true"
ENV COMFYGIT_VOLUME_PATH="/runpod-volume"
ENV COMFYGIT_ACTIVE_ENV="blue"

# RunPod handler entry point
CMD ["/app/start.sh"]
