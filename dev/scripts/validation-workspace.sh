#!/usr/bin/env bash
# validation-workspace.sh - Manage disposable test workspaces for ComfyGit validation
#
# Creates isolated workspaces under /tmp/cg-validate-<name>/ with copies of
# cached data from the shared dev workspace for fast setup.
#
# Usage:
#   validation-workspace.sh create [--comfyui VERSION] [--name NAME]
#   validation-workspace.sh teardown [NAME]
#   validation-workspace.sh list

set -euo pipefail

SHARED_WORKSPACE="/data/projects/comfygit-ai/.comfygit-workspace"
VALIDATE_PREFIX="/tmp/cg-validate"
DEFAULT_COMFYUI="v0.11.0"
DEFAULT_PYTHON="3.12"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  create    Create a fresh validation workspace
  teardown  Remove a validation workspace
  list      List active validation workspaces

Create options:
  --comfyui VERSION   ComfyUI version (default: $DEFAULT_COMFYUI)
  --name NAME         Workspace name (default: val-<timestamp>)
  --no-env            Skip environment creation (workspace only)

Teardown:
  $(basename "$0") teardown <NAME>
  $(basename "$0") teardown --all

Examples:
  $(basename "$0") create --name test-sync
  COMFYGIT_HOME=/tmp/cg-validate-test-sync cg list
  $(basename "$0") teardown test-sync
EOF
}

cmd_create() {
    local name=""
    local comfyui="$DEFAULT_COMFYUI"
    local create_env=true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --name) name="$2"; shift 2 ;;
            --comfyui) comfyui="$2"; shift 2 ;;
            --no-env) create_env=false; shift ;;
            *) echo "Unknown option: $1"; usage; exit 1 ;;
        esac
    done

    if [[ -z "$name" ]]; then
        name="val-$(date +%s)"
    fi

    local ws_path="$VALIDATE_PREFIX-$name"

    if [[ -d "$ws_path" ]]; then
        echo "Error: workspace '$name' already exists at $ws_path"
        exit 1
    fi

    echo "Creating validation workspace: $name"
    echo "  Path: $ws_path"
    echo "  ComfyUI: $comfyui"

    # Initialize workspace structure
    mkdir -p "$ws_path"/{environments,comfygit_cache,logs,models,input,output}

    # Copy caches from shared workspace (full isolation)
    if [[ -d "$SHARED_WORKSPACE/comfygit_cache/comfyui" ]]; then
        echo "  Copying ComfyUI cache..."
        cp -r "$SHARED_WORKSPACE/comfygit_cache/comfyui" "$ws_path/comfygit_cache/comfyui"
    fi

    if [[ -d "$SHARED_WORKSPACE/comfygit_cache/custom_nodes" ]]; then
        echo "  Copying custom node cache..."
        cp -r "$SHARED_WORKSPACE/comfygit_cache/custom_nodes" "$ws_path/comfygit_cache/custom_nodes"
    fi

    if [[ -f "$SHARED_WORKSPACE/comfygit_cache/workflows.db" ]]; then
        cp "$SHARED_WORKSPACE/comfygit_cache/workflows.db" "$ws_path/comfygit_cache/workflows.db"
    fi

    if [[ -f "$SHARED_WORKSPACE/comfygit_cache/models.db" ]]; then
        cp "$SHARED_WORKSPACE/comfygit_cache/models.db" "$ws_path/comfygit_cache/models.db"
    fi

    # Copy registry data
    if [[ -d "$SHARED_WORKSPACE/comfygit_cache/registry" ]]; then
        cp -r "$SHARED_WORKSPACE/comfygit_cache/registry" "$ws_path/comfygit_cache/registry"
    fi

    # Copy metadata
    if [[ -d "$SHARED_WORKSPACE/.metadata" ]]; then
        cp -r "$SHARED_WORKSPACE/.metadata" "$ws_path/.metadata"
    fi

    # Create environment if requested
    if [[ "$create_env" == true ]]; then
        echo "  Creating environment 'default'..."
        COMFYGIT_HOME="$ws_path" uv run --project "$PROJECT_ROOT/packages/cli" \
            cg create default --comfyui "$comfyui" --python "$DEFAULT_PYTHON" --use -y 2>&1 | \
            sed 's/^/    /'
    fi

    echo ""
    echo "Workspace ready. Export these to use:"
    echo "  export COMFYGIT_HOME=$ws_path"
    echo "  export UV_CACHE_DIR=$SHARED_WORKSPACE/uv_cache"
    echo ""
    echo "Or prefix commands:"
    echo "  COMFYGIT_HOME=$ws_path UV_CACHE_DIR=$SHARED_WORKSPACE/uv_cache cg list"
}

cmd_teardown() {
    if [[ $# -eq 0 ]]; then
        echo "Error: specify workspace name or --all"
        usage
        exit 1
    fi

    if [[ "$1" == "--all" ]]; then
        local count=0
        for ws in "$VALIDATE_PREFIX"-*; do
            if [[ -d "$ws" ]]; then
                echo "Removing: $ws"
                rm -rf "$ws"
                ((count++))
            fi
        done
        echo "Removed $count workspace(s)"
        return
    fi

    local name="$1"
    local ws_path="$VALIDATE_PREFIX-$name"

    if [[ ! -d "$ws_path" ]]; then
        echo "Error: workspace '$name' not found at $ws_path"
        exit 1
    fi

    echo "Removing workspace: $name"
    rm -rf "$ws_path"
    echo "Done"
}

cmd_list() {
    local found=false
    for ws in "$VALIDATE_PREFIX"-*; do
        if [[ -d "$ws" ]]; then
            found=true
            local name="${ws#$VALIDATE_PREFIX-}"
            local env_count
            env_count=$(find "$ws/environments" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
            local size
            size=$(du -sh "$ws" 2>/dev/null | cut -f1)
            echo "  $name  ($env_count envs, $size)"
        fi
    done

    if [[ "$found" == false ]]; then
        echo "  No active validation workspaces"
    fi
}

# Main dispatch
case "${1:-}" in
    create) shift; cmd_create "$@" ;;
    teardown) shift; cmd_teardown "$@" ;;
    list) cmd_list ;;
    -h|--help|"") usage ;;
    *) echo "Unknown command: $1"; usage; exit 1 ;;
esac
