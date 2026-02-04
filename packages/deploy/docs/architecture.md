# ComfyGit Deploy - Architecture

## Overview

ComfyGit Deploy is a remote deployment and worker management CLI for ComfyUI. It provides two deployment modes: **cloud-based via RunPod** (managed serverless GPU) and **self-hosted workers** (HTTP API on local infrastructure). Both modes support multi-instance management, configuration persistence, and automatic ComfyUI environment setup.

**Entry point**: `comfygit_deploy.cli:main()` → `cg-deploy` command

## Core Architecture Pattern

**Layer-based with provider abstraction**:
1. **CLI Layer** (`cli.py` + `commands/`) - Argument parsing and command routing
2. **Provider Clients** (`providers/`) - Cloud API abstractions (RunPod, custom workers)
3. **Worker Runtime** (`worker/`) - Self-hosted instance management and HTTP server
4. **Shared Services** (`config.py`, `startup/`) - Configuration and script generation
5. **Domain Objects** (dataclasses in `state.py`) - Instance and state representation

No coupling to specific UI frameworks. All operations async-first with aiohttp.

## Module Organization

| Directory | Purpose | Key Concepts |
|-----------|---------|--------------|
| `cli.py` | Argument parsing and command dispatch | Subcommands, main() entry |
| `config.py` | Persistent configuration storage | DeployConfig, ~/.config/comfygit/deploy/ |
| `commands/` | Command handlers for CLI subcommands | runpod, custom, instances, dev (local pkg setup), worker; also logs, open, wait, start |
| `providers/` | Cloud provider REST/GraphQL clients | RunPodClient, CustomWorkerClient, API abstraction |
| `startup/` | Startup script generation for deployments | generate_startup_script(), deployment IDs |
| `worker/` | Self-hosted worker server and state | WorkerServer, InstanceState, PortAllocator, NativeManager |

## Key Abstractions

### Provider Clients (`providers/`)
- **RunPodClient** - RunPod GraphQL/REST client (pod provisioning, lifecycle, logs)
- **CustomWorkerClient** - HTTP client for self-hosted workers
- Unified interface: async methods for deploy, stop, terminate, logs

### Worker Server (`worker/`)
- **WorkerServer** - aiohttp-based REST API for instance management
- **WorkerState** - Persistent JSON state file tracking all instances
- **InstanceState** - Single instance (ComfyUI process) with port allocation and status
- **PortAllocator** - Reserved port pool (8200-8210) for instance mapping
- **NativeManager** - Launch/monitor native processes (non-Docker fallback)

### Configuration (`config.py`)
- **DeployConfig** - Load/save RunPod API keys and custom worker registry from JSON
- Defaults to `~/.config/comfygit/deploy/config.json`

### Startup Scripts (`startup/`)
- **generate_startup_script()** - Bash script template for ComfyUI + ComfyGit setup on RunPod
- Injects deployment ID, git source, branch, port configuration
- No side effects; pure script generation

## Where to Look

**Adding a new cloud provider**: Copy `providers/runpod.py` pattern → implement HTTP client
**Modifying worker API**: Edit `worker/server.py` route handlers and request/response handling
**State persistence**: `worker/state.py` → InstanceState serialization and WorkerState JSON management
**Configuration**: `config.py` → DeployConfig add new fields → update config schema
**CLI commands**: `commands/{provider}.py` → add handler function → register in `cli.py` subparser
**Instance lifecycle**: `worker/native_manager.py` → launch/monitor/cleanup process management

## Design Patterns

1. **Async-First** - All I/O async; sync wrappers use `asyncio.run()` in CLI commands
2. **Configuration as Code** - Startup scripts are pure functions generating Bash (no template files)
3. **Provider Polymorphism** - Same CLI commands dispatch to different backends (RunPod vs custom)
4. **Persistent State** - Worker state saved to JSON; survives restarts via state reload
5. **Port Allocation** - Reserved port ranges prevent conflicts; allocation persisted with instance
6. **Error Context** - Custom exceptions (RunPodAPIError, CustomWorkerError) with structured details

## Dependencies

- **comfygit** - Core library for environment management
- **aiohttp** - Async HTTP for APIs and worker server
- **zeroconf** - mDNS discovery for worker discovery (MDNSBroadcaster/MDNSScanner)

## Testing Strategy

Tests in `tests/` cover:
- Config load/save roundtrips
- Provider client API mocking
- Worker state serialization
- Port allocation logic
- Startup script generation
- Worker server routes and lifecycle
- Instance lifecycle operations
