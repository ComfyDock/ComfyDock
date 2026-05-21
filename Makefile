# Makefile - Development automation
.PHONY: help install dev test lint format clean show-versions bump-major bump-package check-versions
.PHONY: build-core build-cli build-studio build-all
.PHONY: docs-serve docs-build docs-deploy docs-clean
.PHONY: merge-and-sync
.PHONY: test-cross-platform test-linux test-windows test-platforms

# Default target
help:
	@echo "ComfyGit Development Commands:"
	@echo ""
	@echo "General Commands:"
	@echo "  make install      - Install all packages in development mode"
	@echo "  make dev          - Install local development dependencies"
	@echo "  make test         - Run all tests (local)"
	@echo "  make test-e2e     - Run E2E tests (requires fixtures)"
	@echo "  make lint         - Run linting"
	@echo "  make format       - Format code"
	@echo "  make clean        - Clean build artifacts"
	@echo ""
	@echo "Version Management:"
	@echo "  make show-versions  - Show all package versions"
	@echo "  make check-versions - Check version compatibility"
	@echo "  make bump-version VERSION=X.Y.Z - Bump all packages + update dependencies"
	@echo "  make bump-major VERSION=X - Bump major version for all packages"
	@echo "  make bump-package PACKAGE=core VERSION=X.Y.Z - Bump individual package"
	@echo ""
	@echo "Git Workflow:"
	@echo "  make merge-and-sync [PR=number] - Merge PR and sync dev with main"
	@echo ""
	@echo "Build & Publishing:"
	@echo "  make build-core   - Build comfygit-core package"
	@echo "  make build-cli    - Build comfygit package"
	@echo "  make build-studio - Build bundled Studio frontend"
	@echo "  make build-all    - Build all packages"
	@echo ""
	@echo "Cross-Platform Testing:"
	@echo "  make test-cross-platform  - Run tests on all enabled platforms"
	@echo "  make test-linux           - Run tests on Linux only"
	@echo "  make test-windows         - Run tests on Windows (via SSH)"
	@echo "  make test-platforms       - List available test platforms"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs-serve   - Serve docs locally at http://localhost:8000"
	@echo "  make docs-build   - Build static documentation site"
	@echo "  make docs-deploy  - Deploy docs to GitHub Pages"
	@echo "  make docs-clean   - Clean built documentation files"

# Install all packages in development mode
install:
	uv sync --all-packages

# Alias for local development setup
dev: install

# Run all tests (local)
test:
	uv run pytest packages/core/tests
	uv run pytest packages/cli/tests

# Run E2E tests (requires fixtures)
test-e2e:
	uv run pytest tests/e2e/tests -v

# Cross-platform testing
test-cross-platform:
	@python3 dev/scripts/cross-platform-test.py

test-linux:
	@python3 dev/scripts/cross-platform-test.py --platforms linux

test-windows:
	@python3 dev/scripts/cross-platform-test.py --platforms windows

test-platforms:
	@python3 dev/scripts/cross-platform-test.py --list

# Run linting
lint:
	uv run ruff check packages/

# Format code
format:
	uv run ruff format packages/

# Clean build artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +
	find . -type d -name "build" -exec rm -rf {} +
	rm -rf .coverage htmlcov .pytest_cache

# Version management commands
show-versions:
	@echo "Current package versions:"
	@echo -n "  comfygit-core: " && grep '^version =' packages/core/pyproject.toml | grep -oP 'version = "\K[^"]+'
	@echo -n "  comfygit (cli): " && grep '^version =' packages/cli/pyproject.toml | grep -oP 'version = "\K[^"]+'
	@echo -n "  @comfygit/studio: " && grep '"version":' packages/studio/package.json | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/'

# Check version compatibility
check-versions:
	@uv run python dev/scripts/check-versions.py

# Bump version for coordinated release (lockstep versioning)
# Supports PEP 440 versions: X.Y.Z, X.Y.Z.devN, X.Y.ZaN, X.Y.ZbN, X.Y.ZrcN
bump-version:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make bump-version VERSION=0.3.8"; \
		echo "       make bump-version VERSION=0.3.8.dev1"; \
		exit 1; \
	fi
	@echo "Bumping all release artifacts to version $(VERSION) (lockstep)..."
	@sed -i 's/^version = "[^"]*"/version = "$(VERSION)"/' packages/core/pyproject.toml
	@sed -i 's/^version = "[^"]*"/version = "$(VERSION)"/' packages/cli/pyproject.toml
	@sed -i 's/comfygit-core==[^"]*/comfygit-core==$(VERSION)/' packages/cli/pyproject.toml
	@npm --prefix packages/studio version "$(VERSION)" --no-git-tag-version --allow-same-version >/dev/null
	@echo "✓ Updated all release artifacts to $(VERSION)"
	@echo "✓ Updated CLI dependency: comfygit-core==$(VERSION)"
	@make show-versions

# Bump major version for all packages
bump-major:
	@echo "Bumping release artifacts to major version $(VERSION).0.0"
	@sed -i 's/^version = "[^"]*"/version = "$(VERSION).0.0"/' packages/*/pyproject.toml
	@npm --prefix packages/studio version "$(VERSION).0.0" --no-git-tag-version --allow-same-version >/dev/null
	@echo "Don't forget to update dependency constraints!"

# Bump individual package version
bump-package:
	@if [ -z "$(PACKAGE)" ] || [ -z "$(VERSION)" ]; then \
		echo "Usage: make bump-package PACKAGE=core VERSION=0.2.3"; \
		exit 1; \
	fi
	@sed -i 's/version = "[^"]*"/version = "$(VERSION)"/' packages/$(PACKAGE)/pyproject.toml
	@echo "Updated comfygit-$(PACKAGE) to version $(VERSION)"

# Build individual packages
build-core:
	@echo "Building comfygit-core..."
	@rm -rf dist/
	uv build --package comfygit-core --no-sources
	@echo "✓ Built comfygit-core (see dist/)"

build-cli:
	@$(MAKE) build-studio
	@echo "Building comfygit..."
	@rm -rf dist/
	uv build --package comfygit --no-sources
	@echo "✓ Built comfygit (see dist/)"

build-studio:
	@echo "Building bundled Studio frontend..."
	npm --prefix packages/studio run build
	python3 dev/scripts/sync-studio-static.py
	@echo "✓ Built @comfygit/studio and synced CLI static assets"

build-all:
	@echo "Building all packages..."
	@rm -rf dist/
	uv build --package comfygit-core --no-sources
	@echo "✓ Built comfygit-core"
	npm --prefix packages/studio run build
	python3 dev/scripts/sync-studio-static.py
	@echo "✓ Built @comfygit/studio and synced CLI static assets"
	uv build --package comfygit --no-sources
	@echo "✓ Built comfygit"
	@echo "✓ All release artifacts built"

# Documentation commands
docs-serve:
	@echo "Starting documentation server..."
	@echo "Visit http://localhost:8000"
	cd docs/comfygit-docs && . .venv/bin/activate && mkdocs serve

docs-build:
	@echo "Building documentation..."
	cd docs/comfygit-docs && . .venv/bin/activate && mkdocs build
	@echo "✓ Documentation built (see docs/comfygit-docs/site/)"

docs-deploy:
	@echo "Deploying documentation to GitHub Pages..."
	cd docs/comfygit-docs && . .venv/bin/activate && mkdocs gh-deploy
	@echo "✓ Documentation deployed"

docs-clean:
	@echo "Cleaning documentation build artifacts..."
	rm -rf docs/comfygit-docs/site/
	@echo "✓ Documentation cleaned"

# Git workflow commands
merge-and-sync:
	@if [ -n "$(PR)" ]; then \
		python3 dev/scripts/merge-and-sync.py $(PR); \
	else \
		python3 dev/scripts/merge-and-sync.py; \
	fi
