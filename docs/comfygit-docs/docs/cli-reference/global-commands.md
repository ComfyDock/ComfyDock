# Global Commands

These commands operate at the workspace level or create new environments. Use
`cg <command> -h` for the exact parser help in your installed version.

!!! warning "Reference freshness"
    This page is a source-checked summary for the current docs rewrite. The full
    generated CLI reference is being rebuilt so it can stay synchronized with
    the parser automatically.

## Workspace Setup

```bash
cg init [path] [--models-dir PATH] [--yes]
cg list
cg config --show
cg config --uv-cache PATH
cg auth status
cg auth set civitai [--token-stdin]
cg auth set huggingface [--token-stdin]
cg auth set github [--token-stdin]
cg auth login huggingface [--force]
cg auth migrate
cg auth clear PROVIDER
```

## Create, Import, Export, Materialize

```bash
cg create NAME [--template PATH] [--python VERSION] [--comfyui REF] [--torch-backend BACKEND] [--no-manager] [--use] [--yes]
cg import SOURCE [--name NAME] [--branch REF] [--torch-backend BACKEND] [--models all|required|skip] [--no-manager] [--use] [--yes]
cg export [PATH] [--allow-issues]
cg materialize SOURCE --name NAME [--workspace PATH] [--models-dir PATH] [--branch REF] [--torch-backend BACKEND] [--models all|required|skip] [--with-manager] [--use] [--replace]
```

Use `import` for a human authoring environment. Use `materialize` for
non-interactive runtime or build hydration.

## Analyze

Analyze a workflow file without selecting an environment:

```bash
cg analyze workflow.json
cg analyze workflow.json --json
cg analyze workflow.json --draft-spec
cg analyze workflow.json --online
cg analyze workflow.json --verbose
cg analyze workflow.json --quiet
```

## Models

```bash
cg model index status
cg model index dir PATH
cg model index sync
cg model index list [--duplicates]
cg model index find QUERY
cg model index show IDENTIFIER
cg model download URL [--path RELATIVE_PATH] [--category CATEGORY] [--yes]
cg model add-source [MODEL] [URL]
cg model delete IDENTIFIER [--yes]
```

## Registry, Updates, Debugging

```bash
cg registry status
cg registry update
cg update [--check]
cg debug [-n LINES] [--level DEBUG|INFO|WARNING|ERROR] [--full] [--workspace]
```

## Orchestrator And Workspace Maintenance

```bash
cg orch status [--json]
cg orch restart [--wait]
cg orch kill [--force]
cg orch clean [--dry-run] [--force] [--kill]
cg orch logs [--follow] [-n LINES]
cg workspace cleanup [--force]
```

`cg orchestrator` is an alias for `cg orch`.

## Shell Completion

```bash
cg completion install
cg completion status
cg completion uninstall
```
