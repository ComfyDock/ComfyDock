ARG BASE_IMAGE=nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_PREFER_BINARY=1
ENV PYTHONUNBUFFERED=1
ENV WINDOW_BACKEND=headless
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,video

RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g; s|http://security.ubuntu.com/ubuntu/|https://security.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources

RUN apt-get update -o Acquire::Retries=10 && apt-get install -y \
    -o Acquire::Retries=10 \
    ca-certificates \
    curl \
    ffmpeg \
    git \
    git-lfs \
    libegl1-mesa-dev \
    libgl1 \
    libglib2.0-0 \
    libglvnd-dev \
    libglvnd0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    openssh-client \
    python3-numpy \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    wget \
    xz-utils \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/share/glvnd/egl_vendor.d \
    && printf '%s\n' '{"file_format_version":"1.0.0","ICD":{"library_path":"libEGL_nvidia.so.0"}}' \
      > /usr/share/glvnd/egl_vendor.d/10_nvidia.json

RUN wget -qO- https://astral.sh/uv/install.sh | sh \
    && ln -sf /root/.local/bin/uv /usr/local/bin/uv \
    && ln -sf /root/.local/bin/uvx /usr/local/bin/uvx

RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV VIRTUAL_ENV="/opt/venv"
