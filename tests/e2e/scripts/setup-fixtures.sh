#!/usr/bin/env bash
#
# setup-fixtures.sh - Build E2E test fixture infrastructure
#
# This script creates the shared caches and pre-built workspaces needed for E2E tests.
# First run downloads PyTorch (~2GB), subsequent runs use cached packages.
#
# Usage:
#   ./scripts/setup-fixtures.sh          # Create fixtures (idempotent)
#   ./scripts/setup-fixtures.sh --reset  # Delete and recreate fixtures
#
set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if exists
if [[ -f "$E2E_ROOT/.env" ]]; then
    echo "Loading configuration from .env"
    set -a
    # shellcheck source=/dev/null
    source "$E2E_ROOT/.env"
    set +a
fi

# Configuration with defaults
UV_CACHE_DIR="${E2E_UV_CACHE_DIR:-$E2E_ROOT/.cache/uv}"
COMFYUI_BASE_DIR="${E2E_COMFYUI_BASE_DIR:-$E2E_ROOT/.cache/comfyui-base}"
FIXTURES_DIR="${E2E_FIXTURES_DIR:-$E2E_ROOT/fixtures}"
COMFYUI_VERSION="${E2E_COMFYUI_VERSION:-v0.4.0}"
PYTHON_VERSION="${E2E_PYTHON_VERSION:-3.12}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Phase 1: Create UV cache directory
setup_uv_cache() {
    log_info "Setting up UV cache at: $UV_CACHE_DIR"
    mkdir -p "$UV_CACHE_DIR"
}

# Phase 2: Clone ComfyUI base (if not exists)
setup_comfyui_base() {
    if [[ -d "$COMFYUI_BASE_DIR/.git" ]]; then
        log_info "ComfyUI base already exists at: $COMFYUI_BASE_DIR"
        return 0
    fi

    log_info "Cloning ComfyUI $COMFYUI_VERSION (shallow clone)..."
    mkdir -p "$(dirname "$COMFYUI_BASE_DIR")"
    git clone --branch "$COMFYUI_VERSION" --depth 1 \
        https://github.com/comfyanonymous/ComfyUI.git \
        "$COMFYUI_BASE_DIR"
    log_info "ComfyUI base clone complete"
}

# Phase 3a: Pre-populate ComfyUI cache in workspace
populate_comfyui_cache() {
    local workspace_path="$1"
    local cache_dir="$workspace_path/comfygit_cache/comfyui"
    local store_dir="$cache_dir/store"
    local cache_key="release_${COMFYUI_VERSION}"
    local content_dir="$store_dir/$cache_key/content"

    log_info "Pre-populating ComfyUI cache..."

    # Create cache structure
    mkdir -p "$content_dir"

    # Copy ComfyUI files from base
    cp -r "$COMFYUI_BASE_DIR/." "$content_dir/"

    # Get commit SHA
    local commit_sha
    commit_sha=$(git -C "$content_dir" rev-parse HEAD)

    # Calculate size (portable: works on both GNU and BSD/macOS)
    local size_bytes
    if du -sb "$content_dir" &>/dev/null; then
        size_bytes=$(du -sb "$content_dir" | cut -f1)
    else
        # macOS/BSD: du -sk gives KB, multiply by 1024
        size_bytes=$(($(du -sk "$content_dir" | cut -f1) * 1024))
    fi

    # Create metadata.json
    local cached_at
    cached_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    cat > "$store_dir/$cache_key/metadata.json" << EOF
{
  "cache_key": "$cache_key",
  "cached_at": "$cached_at",
  "size_bytes": $size_bytes,
  "content_hash": "prebuilt",
  "version": "$COMFYUI_VERSION",
  "version_type": "release",
  "commit_sha": "$commit_sha"
}
EOF

    # Create index.json
    cat > "$cache_dir/index.json" << EOF
{
  "version": "1.0",
  "content_type": "comfyui",
  "updated_at": "$cached_at",
  "items": {
    "$cache_key": {
      "cache_key": "$cache_key",
      "cached_at": "$cached_at",
      "size_bytes": $size_bytes,
      "content_hash": "prebuilt",
      "version": "$COMFYUI_VERSION",
      "version_type": "release",
      "commit_sha": "$commit_sha"
    }
  }
}
EOF

    log_info "ComfyUI cache populated with $COMFYUI_VERSION"
}

# Phase 3: Create fixture workspace
create_fixture() {
    local fixture_name="$1"
    local fixture_path="$FIXTURES_DIR/$fixture_name"

    if [[ -d "$fixture_path" ]]; then
        log_info "Fixture '$fixture_name' already exists"
        return 0
    fi

    log_info "Creating fixture workspace: $fixture_name"
    mkdir -p "$FIXTURES_DIR"

    # Initialize workspace
    cg init "$fixture_path"

    # Pre-populate ComfyUI cache
    populate_comfyui_cache "$fixture_path"

    # Create default environment with shared UV cache
    log_info "Creating 'default' environment (this may take a while on first run)..."
    UV_CACHE_DIR="$UV_CACHE_DIR" cg -H "$fixture_path" create default \
        --comfyui "$COMFYUI_VERSION" \
        --python "$PYTHON_VERSION" \
        --yes

    log_info "Fixture '$fixture_name' created successfully"
}

# Reset: Remove all fixtures
reset_fixtures() {
    log_warn "Resetting fixtures..."
    if [[ -d "$FIXTURES_DIR" ]]; then
        rm -rf "$FIXTURES_DIR"
        log_info "Removed: $FIXTURES_DIR"
    fi
}

# Main
main() {
    local do_reset=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --reset)
                do_reset=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [--reset]"
                echo ""
                echo "Options:"
                echo "  --reset    Remove and recreate all fixtures"
                echo "  -h, --help Show this help"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    echo "========================================"
    echo "E2E Fixture Setup"
    echo "========================================"
    echo "UV Cache:     $UV_CACHE_DIR"
    echo "ComfyUI Base: $COMFYUI_BASE_DIR"
    echo "Fixtures:     $FIXTURES_DIR"
    echo "ComfyUI Ver:  $COMFYUI_VERSION"
    echo "Python Ver:   $PYTHON_VERSION"
    echo "========================================"

    # Reset if requested
    if $do_reset; then
        reset_fixtures
    fi

    # Run setup phases
    setup_uv_cache
    setup_comfyui_base
    create_fixture "basic"

    echo ""
    echo "========================================"
    log_info "Setup complete!"
    echo "========================================"
    echo ""
    echo "Fixture ready at: $FIXTURES_DIR/basic"
    echo ""
    echo "To verify:"
    echo "  cg -H $FIXTURES_DIR/basic status"
    echo ""
    echo "To run tests:"
    echo "  uv run pytest tests/e2e/tests/smoke/ -v"
    echo ""
}

main "$@"
