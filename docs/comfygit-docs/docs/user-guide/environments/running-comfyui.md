# Running ComfyUI

> Learn how to start, stop, and manage the ComfyUI web interface in your environments.

## Prerequisites

* Environment created — `cg create my-env`
* Environment set as active — `cg use my-env` (or use `-e` flag)

## Basic usage

Start ComfyUI in your active environment:

```bash
cg run
```

**Output:**

```
🎮 Starting ComfyUI in environment: my-env
```

ComfyUI then outputs its startup logs and opens on **http://localhost:8188**

!!! tip "First run"
    The first time you run ComfyUI in an environment, it may take a few seconds to initialize. Subsequent runs are faster.

## Passing ComfyUI args

Use `--` to pass arguments directly to ComfyUI when you need to avoid conflicts with ComfyGit flags:

```bash
cg run --all-extras -- --listen 0.0.0.0
```

## Optional extras during run

`cg run` performs a sync before launching. If you need optional extras for this run, pass them explicitly:

```bash
cg run --extra cuda
```

Or install all optional extras:

```bash
cg run --all-extras
```

You can also set default extras that apply to every sync (including `cg run` and `cg node add`):

```bash
cg env-config extras add cuda
```

## Running in specific environment

If you don't have an active environment set:

```bash
cg -e my-env run
```

Or switch environments:

```bash
# Set active
cg use my-env

# Then run
cg run
```

## Accessing ComfyUI

Once running, open your browser to:

```
http://localhost:8188
```

**You should see:**

* ComfyUI's web interface
* Default workflow loaded
* Node library on the left
* Canvas in the center

## Stopping ComfyUI

ComfyUI runs in the foreground by default. To stop it:

**Press Ctrl+C** in the terminal

```
^C
✓ ComfyUI stopped
```

## Running in the background

### Using &

Run ComfyUI in the background:

```bash
cg run &
```

**To stop:**

```bash
# Find the process
ps aux | grep ComfyUI

# Kill it
kill <PID>
```

### Using screen

More reliable for long-running sessions:

```bash
# Start a screen session
screen -S comfy

# Run ComfyUI
cg run

# Detach with Ctrl+A, then D
```

**To reattach:**

```bash
screen -r comfy
```

**To stop:**

```bash
# Reattach
screen -r comfy

# Press Ctrl+C
# Exit screen
exit
```

### Using tmux

Another option for persistent sessions:

```bash
# Start tmux session
tmux new -s comfy

# Run ComfyUI
cg run

# Detach with Ctrl+B, then D
```

**To reattach:**

```bash
tmux attach -t comfy
```

**To stop:**

```bash
# Reattach
tmux attach -t comfy

# Press Ctrl+C
# Exit tmux
exit
```

## Passing arguments to ComfyUI

ComfyGit passes all arguments after `run` directly to ComfyUI's `main.py`:

### Change port

```bash
# Run on port 8080
cg run --port 8080
```

Access at: `http://localhost:8080`

### Listen on all interfaces

```bash
# Allow external access
cg run --listen 0.0.0.0
```

!!! warning "Security"
    Only use `--listen 0.0.0.0` on trusted networks. This exposes ComfyUI to your entire network.

### Auto-launch browser

```bash
# Open browser automatically
cg run --auto-launch
```

### Enable CORS

```bash
# Allow cross-origin requests
cg run --enable-cors-header
```

### Disable GPU

```bash
# Force CPU-only execution
cg run --cpu
```

Useful for testing or if GPU is in use.

### Multiple arguments

Combine any ComfyUI arguments:

```bash
cg run --port 8080 --listen 0.0.0.0 --auto-launch
```

**Output:**

```
🎮 Starting ComfyUI in environment: my-env
   Arguments: --port 8080 --listen 0.0.0.0 --auto-launch
```

!!! tip "ComfyUI arguments"
    For a full list of ComfyUI arguments, run:
    ```bash
    cg run -- --help
    ```
    The `--` separator tells cg to pass all remaining arguments to ComfyUI.

## Running multiple environments simultaneously

You can run different environments on different ports:

```bash
# Terminal 1: production on default port
cg -e production run

# Terminal 2: testing on port 8189
cg -e testing run --port 8189

# Terminal 3: dev on port 8190
cg -e dev run --port 8190
```

Access each at:

* Production: `http://localhost:8188`
* Testing: `http://localhost:8189`
* Dev: `http://localhost:8190`

!!! warning "Resource usage"
    Running multiple ComfyUI instances simultaneously uses significant GPU memory. You may need to reduce batch sizes or use CPU mode for secondary instances.

## Checking logs

If ComfyUI fails to start or behaves unexpectedly:

### ComfyUI output

ComfyUI prints logs directly to your terminal when run in the foreground. Look for:

* **Errors during startup** — Missing dependencies, port conflicts
* **Model loading issues** — Missing models, corrupt files
* **Custom node errors** — Failed imports, missing packages

### ComfyGit logs

For environment-level issues:

```bash
# Show recent logs
cg debug -n 50

# Show all logs
cg debug

# Follow logs in real-time
tail -f ~/comfygit/logs/comfygit.log
```

## Common scenarios

### Quick testing

```bash
# Start, test, stop
cg run
# Use ComfyUI...
# Ctrl+C when done
```

### Long-running server

```bash
# Use screen or tmux
screen -S comfy
cg run

# Detach: Ctrl+A, D
# ComfyUI keeps running
```

### Development workflow

```bash
# Terminal 1: Run ComfyUI
cg run

# Terminal 2: Make changes, test, commit
cg node add new-node
# Test in browser...
cg commit -m "Added new node"
```

### Testing workflow files

```bash
# Start ComfyUI
cg run

# Open http://localhost:8188
# Load workflow from ComfyUI/user/default/workflows/
# Make changes in browser
# Save workflow
# Stop ComfyUI (Ctrl+C)

# Check status
cg status
# Will show modified workflow

# Commit if good
cg commit -m "Updated workflow"
```

## Troubleshooting

### Port already in use

**Symptom:** `Address already in use` error on port 8188

**Solutions:**

```bash
# Find what's using port 8188
lsof -i :8188

# Kill the process
kill <PID>

# Or use a different port
cg run --port 8189
```

### GPU out of memory

**Symptom:** CUDA out of memory errors

**Solutions:**

```bash
# Force CPU mode
cg run --cpu

# Or close other GPU applications
# Or reduce batch size in ComfyUI
# Or use a smaller model
```

### Custom nodes not loading

**Symptom:** "Failed to import custom node" in logs

**Solutions:**

```bash
# Stop ComfyUI (Ctrl+C)

# Repair environment
cg repair

# Restart ComfyUI
cg run
```

### Models not found

**Symptom:** "Model not found" errors in ComfyUI

**Solutions:**

```bash
# Check model symlink
ls -la ~/comfygit/environments/my-env/ComfyUI/models

# Should show symlink to workspace models
# If not, recreate environment or check workspace init

# Sync model index
cg model index sync

# Check where ComfyUI expects models
# They should be in ~/comfygit/models/<category>/
```

### ComfyUI crashes immediately

**Symptom:** ComfyUI starts then exits with error

**Solutions:**

```bash
# Check environment is synced
cg status

# Repair if needed
cg repair

# Check for Python dependency conflicts
cg py list

# Try running Python directly to see error
cd ~/comfygit/environments/my-env/ComfyUI
~/comfygit/environments/my-env/.venv/bin/python main.py
```

### Can't access from another device

**Symptom:** Can access `http://localhost:8188` but not from phone/tablet

**Solutions:**

```bash
# Run with listen flag
cg run --listen 0.0.0.0

# Find your machine's IP
# macOS/Linux
ifconfig | grep inet

# Then access from other device
http://<your-ip>:8188
```

!!! warning "Firewall"
    You may need to allow port 8188 through your firewall for external access.

## Next steps

Now that ComfyUI is running:

* **[Add custom nodes](../custom-nodes/adding-nodes.md)** — Extend functionality
* **[Manage workflows](../workflows/workflow-tracking.md)** — Track and version workflows
* **[Commit changes](version-control.md)** — Save your configuration

## See also

* [ComfyUI Documentation](https://github.com/comfyanonymous/ComfyUI) — Official ComfyUI docs
* [CLI Reference](../../cli-reference/environment-commands.md#run) — Complete run command documentation
* [Troubleshooting](../../troubleshooting/common-issues.md) — More solutions
