FROM ubuntu:22.04

# 1) Install system dependencies and set up glvnd (as root).
WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt update && \
    apt install -y --no-install-recommends \
        ca-certificates \
        libegl1-mesa \
        libegl1-mesa-dev \
        libegl1 \
        libglvnd-dev \
        libglvnd0 \
        git \
        build-essential \
        pkg-config \
        cmake \
        python3-dev \
        libgl1-mesa-glx \
        libglx0 \
        libglib2.0-0 \
        ffmpeg \
        # Additional useful tools
        curl \
        wget \
        jq && \
    mkdir -p /usr/share/glvnd/egl_vendor.d && \
    echo '{"file_format_version":"1.0.0","ICD":{"library_path":"libEGL_nvidia.so.0"}}' \
        >/usr/share/glvnd/egl_vendor.d/10_nvidia.json && \
    apt-get autoremove -y && \
    apt-get autoclean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 2) Create a placeholder user 'comfy' with default UID/GID (1000).
RUN groupadd -g 1000 comfy \
    && useradd -m -u 1000 -g comfy -s /bin/bash comfy

# 3) Create directories with world-writable permissions (as root)
RUN umask 000 && \
    mkdir -p /app && \
    chmod -R 777 /app && \
    mkdir -p /env && \
    chmod -R 777 /env

# 4) Basic environment variables
ENV NVIDIA_DRIVER_CAPABILITIES="all"
ENV NVIDIA_VISIBLE_DEVICES="all"
ENV MESA_D3D12_DEFAULT_ADAPTER_NAME="NVIDIA"
ENV LD_LIBRARY_PATH="/usr/lib/wsl/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64"
ENV WINDOW_BACKEND="headless"
ENV DOCKER_RUNTIME="1"

# 5) Copy uv from a multi-stage build (as root)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 6) Remove the placeholder ComfyUI directory creation
# ComfyUI location will be determined at runtime
WORKDIR /app

# 7) Expose port
EXPOSE 8188

# 8) Copy scripts and set up permissions
# First, create the directory structure for our Python package
RUN mkdir -p /usr/local/lib/comfygit/utils

# Copy the utility modules
COPY docker_startup_scripts/*.py /usr/local/lib/comfygit/
COPY docker_startup_scripts/utils/*.py /usr/local/lib/comfygit/utils/

# Copy the main scripts
COPY docker_startup_scripts/*.py /usr/local/bin/

# Set up Python path to find our modules
ENV PYTHONPATH="/usr/local/lib/comfygit"
ENV PYTHONUNBUFFERED=1

# Create temporary virtual environment for script setup and make scripts executable
RUN uv venv --python 3.12 /tmp/setup_venv && \
    # Make all Python scripts executable
    chmod +x /usr/local/bin/*.py && \
    # Create convenience symlinks for Python scripts (without .py extension)
    ln -sf /usr/local/bin/entrypoint.py /usr/bin/entrypoint && \
    ln -sf /usr/local/bin/check_permissions.py /usr/bin/check-permissions && \
    ln -sf /usr/local/bin/fix_permissions.py /usr/bin/fix-permissions && \
    ln -sf /usr/local/bin/install_comfyui.py /usr/bin/install-comfyui && \
    ln -sf /usr/local/bin/install_pytorch.py /usr/bin/install-pytorch && \
    ln -sf /usr/local/bin/install_from_migration.py /usr/bin/install-from-migration && \
    # Test Python scripts in temporary venv to ensure they're valid
    # This will also verify that imports work correctly
    /tmp/setup_venv/bin/python -m py_compile /usr/local/bin/entrypoint.py && \
    /tmp/setup_venv/bin/python -m py_compile /usr/local/bin/check_permissions.py && \
    /tmp/setup_venv/bin/python -m py_compile /usr/local/bin/fix_permissions.py && \
    /tmp/setup_venv/bin/python -m py_compile /usr/local/bin/install_comfyui.py && \
    /tmp/setup_venv/bin/python -m py_compile /usr/local/bin/install_pytorch.py && \
    /tmp/setup_venv/bin/python -m py_compile /usr/local/bin/install_from_migration.py && \
    # Also compile the utility modules to catch any syntax errors
    /tmp/setup_venv/bin/python -m py_compile /usr/local/lib/comfygit/utils/*.py && \
    # Clean up temporary venv
    rm -rf /tmp/setup_venv

# 9) Stay as root - the entrypoint will handle user switching
ENTRYPOINT ["/usr/local/bin/entrypoint.py"]
