# Environment Commands

Environment commands operate on the active environment or the one selected with
`-e`.

```bash
cg -e my-env status
```

## Run, Serve, Sync, Repair

```bash
cg run [--no-sync] [--torch-backend BACKEND] [--extra EXTRA] [--all-extras] [--overlay NAME] [-- COMFYUI_ARGS...]
cg serve [--host HOST] [--port PORT] [--comfy-url URL]
cg serve [--role studio|proxy] [--executor local|proxy] [--proxy-url URL] [--proxy-token TOKEN]
cg serve [--callback-url URL] [--callback-token TOKEN] [--artifact-dir PATH]
cg serve [--max-request-mb MB] [--run-timeout-seconds SECONDS]
cg serve [--state ephemeral|local] [--gallery private|shared] [--state-db PATH]
cg sync [--torch-backend BACKEND] [--extra EXTRA] [--all-extras] [--overlay NAME] [--verbose]
cg repair [--yes] [--models all|required|skip]
cg status [--verbose]
cg manifest [--pretty] [--section SECTION] [--ide [CMD]]
```

`cg run` launches ComfyUI. `cg serve` fronts an already running ComfyUI server
with workflow contract endpoints and Studio.

## Status

```bash
cg status [--verbose]
```

This heading is kept as a direct link target for troubleshooting pages. The
command is part of the main run/sync/status group above.

## Repair

```bash
cg repair [--yes] [--models all|required|skip]
```

This heading is kept as a direct link target for repair guidance. Use `repair`
when local runtime state has drifted from the tracked environment manifest.

## Local Runtime Configuration

```bash
cg env-config torch-backend show
cg env-config torch-backend set BACKEND
cg env-config torch-backend detect
cg env-config extras show
cg env-config extras add EXTRA [EXTRA...]
cg env-config extras remove EXTRA [EXTRA...]
```

## Overlays

```bash
cg overlay list [--active]
cg overlay show NAME
cg overlay enable NAME
cg overlay disable NAME
cg overlay create [NAME] [--local]
```

Use local overlays for machine-specific dependency sources, indexes, and
temporary package changes.

## Git History

```bash
cg log [-n N] [--verbose]
cg commit [-m MESSAGE] [--auto] [--allow-issues] [--yes]
cg checkout [REF] [-b BRANCH] [--yes] [--force]
cg branch [NAME] [-d] [-D]
cg switch BRANCH [-c]
cg reset [REF] [--mixed|--soft|--hard] [--yes]
cg merge BRANCH [--preview] [--auto-resolve mine|theirs]
cg revert COMMIT
```

Use `revert` to create a new commit that undoes an older commit. Use `reset
--hard` only when you intentionally want to discard local changes.

## Remotes

```bash
cg remote add NAME URL
cg remote remove NAME
cg remote list
cg push [-r REMOTE] [--force]
cg pull [-r REMOTE] [-b BRANCH] [--models all|required|skip] [--force] [--preview] [--auto-resolve mine|theirs] [--torch-backend BACKEND]
```

`origin` is the default remote for push and pull.

## Python Dependencies

```bash
cg py add PACKAGE [PACKAGE...]
cg py add -r requirements.txt
cg py remove PACKAGE [PACKAGE...]
cg py list [--all]
cg py remove-group GROUP
cg py uv <UV_ARGS...>
```

## Constraints

```bash
cg constraint add PACKAGE [PACKAGE...]
cg constraint list
cg constraint remove PACKAGE [PACKAGE...]
```

## Manager And Metadata

```bash
cg manager status
cg manager update [--version VERSION] [--yes]
cg metadata refresh
cg doctor [--check-only]
```
