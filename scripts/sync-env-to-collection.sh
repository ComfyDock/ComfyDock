#!/bin/bash
# sync-env-to-collection - Sync active ComfyGit environment to examples collection
#
# Usage:
#   sync-env-to-collection <path-to-examples-repo> [-m <message>]
#
# Examples:
#   sync-env-to-collection ~/comfygit-examples
#   sync-env-to-collection ~/comfygit-examples -m "feat: add new workflow"
#
# What it syncs (whitelist):
#   - workflows/       (all workflow files)
#   - pyproject.toml   (environment definition)
#   - .python-version  (Python version)
#   - .gitignore       (git ignore rules)
#   - uv.lock          (dependency lock file)
#
# What it preserves:
#   - README.md        (documentation)
#   - Any other custom files

set -euo pipefail

# Whitelist of files/directories to sync from .cec
SYNC_ITEMS=(
    "workflows"
    "pyproject.toml"
    ".python-version"
    ".gitignore"
    "uv.lock"
)

# Parse arguments
EXAMPLES_REPO=""
COMMIT_MESSAGE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -m)
            COMMIT_MESSAGE="$2"
            shift 2
            ;;
        *)
            EXAMPLES_REPO="$1"
            shift
            ;;
    esac
done

if [ -z "$EXAMPLES_REPO" ]; then
    echo "Usage: sync-env-to-collection <path-to-examples-repo> [-m <message>]"
    exit 1
fi

# Detect COMFYGIT_HOME
COMFYGIT_HOME="${COMFYGIT_HOME:-$HOME/comfygit}"
echo "📂 ComfyGit workspace: $COMFYGIT_HOME"

# Read workspace.json to get active environment
WORKSPACE_FILE="$COMFYGIT_HOME/.metadata/workspace.json"
if [ ! -f "$WORKSPACE_FILE" ]; then
    echo "❌ No workspace.json found at $WORKSPACE_FILE"
    echo "   Is this a valid ComfyGit workspace?"
    exit 1
fi

# Extract active environment (handle missing jq gracefully)
if command -v jq &> /dev/null; then
    ACTIVE_ENV=$(jq -r '.active_environment' "$WORKSPACE_FILE")
else
    # Fallback to grep/sed if jq not installed
    ACTIVE_ENV=$(grep -o '"active_environment"[[:space:]]*:[[:space:]]*"[^"]*"' "$WORKSPACE_FILE" | sed 's/.*: *"\([^"]*\)".*/\1/')
fi

if [ -z "$ACTIVE_ENV" ] || [ "$ACTIVE_ENV" = "null" ] || [ "$ACTIVE_ENV" = "" ]; then
    echo "❌ No active environment set"
    echo "   Run: comfygit activate <environment>"
    exit 1
fi

echo "✓ Active environment: $ACTIVE_ENV"

# Validate environment exists
ENV_PATH="$COMFYGIT_HOME/environments/$ACTIVE_ENV"
if [ ! -d "$ENV_PATH" ]; then
    echo "❌ Environment directory not found: $ENV_PATH"
    exit 1
fi

CEC_PATH="$ENV_PATH/.cec"
if [ ! -d "$CEC_PATH" ]; then
    echo "❌ .cec directory not found: $CEC_PATH"
    exit 1
fi

echo "✓ Found .cec at: $CEC_PATH"

# Check for uncommitted changes in .cec (warn but continue)
if [ -d "$CEC_PATH/.git" ]; then
    cd "$CEC_PATH"
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        echo "⚠️  Warning: .cec has uncommitted changes"
        echo "   Consider running: comfygit commit -m 'message' first"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# Prepare target directory
EXAMPLES_DIR="$EXAMPLES_REPO/$ACTIVE_ENV"
if [ ! -d "$EXAMPLES_DIR" ]; then
    echo "📁 Creating new directory: $EXAMPLES_DIR"
    mkdir -p "$EXAMPLES_DIR"
fi

# Sync whitelisted items
echo "📋 Syncing whitelisted items:"
for item in "${SYNC_ITEMS[@]}"; do
    SRC="$CEC_PATH/$item"
    DST="$EXAMPLES_DIR/$item"

    if [ -e "$SRC" ]; then
        echo "   • $item"
        if [ -d "$SRC" ]; then
            # Directory: remove old, copy new
            rm -rf "$DST"
            cp -r "$SRC" "$DST"
        else
            # File: just copy (overwrite)
            cp "$SRC" "$DST"
        fi
    fi
done

echo "✓ Content synced"

# Show git status
cd "$EXAMPLES_REPO"
if [ -d ".git" ]; then
    if [ -n "$(git status --porcelain "$ACTIVE_ENV" 2>/dev/null)" ]; then
        echo ""
        echo "📝 Changes detected:"
        git status --short "$ACTIVE_ENV"
    else
        echo "✓ No changes (content already up to date)"
    fi

    # Optionally commit
    if [ -n "$COMMIT_MESSAGE" ]; then
        if [ -n "$(git status --porcelain "$ACTIVE_ENV" 2>/dev/null)" ]; then
            echo ""
            echo "📝 Committing..."
            git add "$ACTIVE_ENV"
            git commit -m "$COMMIT_MESSAGE"
            echo "✓ Committed: $COMMIT_MESSAGE"
        else
            echo "ℹ️  No changes to commit"
        fi
    else
        echo ""
        echo "ℹ️  Changes ready. To commit:"
        echo "   cd $EXAMPLES_REPO"
        echo "   git add $ACTIVE_ENV"
        echo "   git commit -m 'your message'"
        echo ""
        echo "Or run: $(basename "$0") $EXAMPLES_REPO -m 'your message'"
    fi
else
    echo "⚠️  Not a git repository. Changes synced but not tracked."
fi

echo ""
echo "✅ Done! Environment '$ACTIVE_ENV' synced to: $EXAMPLES_DIR"
