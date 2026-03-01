"""
ComfyGit Serverless Handler for RunPod

Manages a ComfyUI instance on a persistent network volume and processes
workflow execution requests via the RunPod serverless SDK.
"""

import json
import logging
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
import websocket

# ── Logging ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("handler")

# ── Configuration ─────────────────────────────────────────────────────

COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188
COMFY_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"

VOLUME_PATH = os.environ.get("COMFYGIT_VOLUME_PATH", "/runpod-volume")
REPO = os.environ.get("COMFYGIT_REPO", "")
REPO_REF = os.environ.get("COMFYGIT_REPO_REF", "main")
LOWVRAM = os.environ.get("COMFYGIT_LOWVRAM", "true").lower() == "true"

# How long to wait for ComfyUI to become ready
COMFY_STARTUP_TIMEOUT = 300  # 5 minutes
COMFY_POLL_INTERVAL = 0.5  # seconds

# ── Built-in Workflow Builders ────────────────────────────────────────

def build_zimage_prompt(
    prompt: str = "a beautiful landscape",
    width: int = 1024,
    height: int = 1024,
    steps: int = 12,
    seed: int | None = None,
    cfg: float = 1.0,
    sampler: str = "euler",
    scheduler: str = "simple",
    denoise: float = 1.0,
) -> dict:
    """Build the ComfyUI API-format prompt for the Z-Image workflow."""
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "z_image_turbo_bf16.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "4": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["16", 0], "vae": ["2", 0]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["14", 0]},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyUI", "images": ["4", 0]},
        },
        "14": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_4b.safetensors",
                "type": "lumina2",
                "device": "default",
            },
        },
        "15": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "16": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["6", 0],
                "negative": ["6", 0],
                "latent_image": ["15", 0],
                "seed": seed,
                "control_after_generate": "fixed",
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": denoise,
            },
        },
    }


# Registry of built-in workflow builders
WORKFLOW_BUILDERS = {
    "z-image": build_zimage_prompt,
}


# ── Global State ──────────────────────────────────────────────────────

comfy_process: subprocess.Popen | None = None
ab_manager = None  # Initialized in setup()


# ── ComfyUI Process Management ───────────────────────────────────────

def get_comfyui_cmd() -> list[str]:
    """Build the ComfyUI launch command."""
    comfyui_path = ab_manager.active_comfyui_path()
    venv_python = ab_manager.active_env_path() / ".venv" / "bin" / "python"

    cmd = [
        str(venv_python),
        "-u",
        str(comfyui_path / "main.py"),
        "--listen", COMFY_HOST,
        "--port", str(COMFY_PORT),
        "--disable-auto-launch",
        "--disable-metadata",
    ]

    if LOWVRAM:
        cmd.append("--lowvram")

    # Add extra model paths for the shared volume models
    extra_paths = ab_manager.volume_path / "extra_model_paths.yaml"
    if extra_paths.exists():
        cmd.extend(["--extra-model-paths-config", str(extra_paths)])

    return cmd


def start_comfyui() -> bool:
    """Start ComfyUI as a subprocess and wait for it to be ready."""
    global comfy_process

    cmd = get_comfyui_cmd()
    logger.info(f"Starting ComfyUI: {' '.join(cmd)}")

    comfy_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Start a thread to log ComfyUI output
    import threading

    def log_output():
        for line in comfy_process.stdout:
            line = line.rstrip()
            if line:
                logger.info(f"[ComfyUI] {line}")

    log_thread = threading.Thread(target=log_output, daemon=True)
    log_thread.start()

    # Wait for ComfyUI to become ready
    return wait_for_comfyui()


def wait_for_comfyui() -> bool:
    """Poll ComfyUI's API until it responds."""
    logger.info(f"Waiting for ComfyUI at {COMFY_URL} ...")
    start = time.time()

    while time.time() - start < COMFY_STARTUP_TIMEOUT:
        try:
            resp = requests.get(f"{COMFY_URL}/system_stats", timeout=5)
            if resp.status_code == 200:
                elapsed = time.time() - start
                logger.info(f"ComfyUI ready in {elapsed:.1f}s")
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass

        # Check if process died
        if comfy_process and comfy_process.poll() is not None:
            logger.error(f"ComfyUI process exited with code {comfy_process.returncode}")
            return False

        time.sleep(COMFY_POLL_INTERVAL)

    logger.error(f"ComfyUI did not start within {COMFY_STARTUP_TIMEOUT}s")
    return False


def stop_comfyui():
    """Stop the ComfyUI subprocess."""
    global comfy_process
    if comfy_process and comfy_process.poll() is None:
        logger.info("Stopping ComfyUI...")
        comfy_process.terminate()
        try:
            comfy_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            comfy_process.kill()
        comfy_process = None


# ── Workflow Execution ────────────────────────────────────────────────

def load_workflow(workflow_name: str) -> dict | None:
    """Load a workflow JSON from the active environment."""
    workflows_dir = ab_manager.active_comfyui_path() / "user" / "default" / "workflows"
    workflow_file = workflows_dir / f"{workflow_name}.json"

    if not workflow_file.exists():
        # Try without extension
        for f in workflows_dir.glob(f"{workflow_name}*"):
            if f.suffix == ".json":
                workflow_file = f
                break

    if not workflow_file.exists():
        logger.error(f"Workflow not found: {workflow_name} in {workflows_dir}")
        available = [f.stem for f in workflows_dir.glob("*.json")] if workflows_dir.exists() else []
        logger.info(f"Available workflows: {available}")
        return None

    with open(workflow_file) as f:
        return json.load(f)


def apply_overrides(workflow: dict, overrides: dict) -> dict:
    """
    Apply parameter overrides to a workflow.

    Overrides format:
    {
        "node_id": {
            "widget_name": "value",
            ...
        }
    }

    Common overrides for Z-Image:
    {
        "3": {"text": "a cat in space"},      # positive prompt
        "6": {"seed": 42},                      # sampler seed
        "6": {"steps": 12},                     # sampler steps
        "8": {"width": 1024, "height": 1024},  # image dimensions
    }
    """
    for node_id, widgets in overrides.items():
        if node_id in workflow:
            inputs = workflow[node_id].get("inputs", {})
            inputs.update(widgets)
            workflow[node_id]["inputs"] = inputs
        else:
            logger.warning(f"Override target node {node_id} not found in workflow")
    return workflow


def queue_workflow(workflow: dict) -> tuple[str, str]:
    """
    Queue a workflow for execution via ComfyUI API.
    Returns (prompt_id, client_id).
    """
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": workflow,
        "client_id": client_id,
    }

    resp = requests.post(
        f"{COMFY_URL}/prompt",
        json=payload,
        timeout=30,
    )

    if resp.status_code == 400:
        error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise ValueError(f"Workflow validation failed: {error_data}")

    resp.raise_for_status()
    data = resp.json()
    prompt_id = data["prompt_id"]
    logger.info(f"Queued workflow: prompt_id={prompt_id}")
    return prompt_id, client_id


def wait_for_completion(prompt_id: str, client_id: str,
                        timeout: int = 300) -> dict:
    """
    Wait for a workflow to complete via websocket.
    Returns the output data.
    """
    ws_url = f"ws://{COMFY_HOST}:{COMFY_PORT}/ws?clientId={client_id}"
    ws = websocket.WebSocket()
    ws.connect(ws_url, timeout=10)

    start = time.time()
    try:
        while time.time() - start < timeout:
            try:
                msg = ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    msg_type = data.get("type")

                    if msg_type == "executing":
                        exec_data = data.get("data", {})
                        if exec_data.get("prompt_id") == prompt_id:
                            if exec_data.get("node") is None:
                                # Execution complete
                                logger.info(f"Workflow complete ({time.time()-start:.1f}s)")
                                break

                    elif msg_type == "execution_error":
                        error_data = data.get("data", {})
                        raise RuntimeError(
                            f"Execution error: {error_data.get('exception_message', 'unknown')}"
                        )

                    elif msg_type == "progress":
                        prog = data.get("data", {})
                        logger.debug(
                            f"Progress: {prog.get('value', '?')}/{prog.get('max', '?')}"
                        )

            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException:
                logger.warning("WebSocket closed, reconnecting...")
                ws = websocket.WebSocket()
                ws.connect(ws_url, timeout=10)
    finally:
        ws.close()

    # Fetch the output
    resp = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10)
    resp.raise_for_status()
    history = resp.json()

    if prompt_id not in history:
        raise RuntimeError("Prompt not found in history after completion")

    return history[prompt_id]


def collect_outputs(history_entry: dict) -> list[dict]:
    """
    Extract output file references from a completed workflow's history.
    Returns list of {filename, subfolder, type} dicts.
    """
    outputs = []
    for node_id, node_output in history_entry.get("outputs", {}).items():
        # Image outputs
        for img in node_output.get("images", []):
            outputs.append({
                "type": "image",
                "filename": img["filename"],
                "subfolder": img.get("subfolder", ""),
                "format": img.get("type", "output"),
            })
        # Audio outputs
        for aud in node_output.get("audio", []):
            outputs.append({
                "type": "audio",
                "filename": aud["filename"],
                "subfolder": aud.get("subfolder", ""),
                "format": aud.get("type", "output"),
            })
    return outputs


def fetch_output_as_base64(filename: str, subfolder: str = "",
                           output_type: str = "output") -> str:
    """Download an output file from ComfyUI and return as base64."""
    import base64

    params = {
        "filename": filename,
        "subfolder": subfolder,
        "type": output_type,
    }
    resp = requests.get(f"{COMFY_URL}/view", params=params, timeout=30)
    resp.raise_for_status()
    return base64.b64encode(resp.content).decode("utf-8")


# ── RunPod Handler ────────────────────────────────────────────────────

def handler(job: dict) -> dict:
    """
    RunPod serverless handler.

    Input format:
    {
        "workflow_name": "z-image",        # Name of workflow file (without .json)
        "prompt": "a cat in space",        # Shortcut: sets positive prompt text
        "seed": 42,                        # Shortcut: sets sampler seed
        "width": 1024,                     # Shortcut: image width
        "height": 1024,                    # Shortcut: image height
        "steps": 12,                       # Shortcut: sampling steps
        "overrides": {                     # Advanced: raw node overrides
            "3": {"text": "custom prompt"},
        },
        "workflow": { ... },               # Advanced: full workflow JSON (overrides workflow_name)
        "return_base64": true,             # Return output as base64 (default: true)
    }

    Special commands (instead of inference):
    {
        "command": "status"                # Return environment status
        "command": "update"                # Trigger A/B update
    }
    """
    job_input = job.get("input", {})

    # Handle special commands
    command = job_input.get("command")
    if command == "status":
        return ab_manager.status()
    elif command == "update":
        return ab_manager.update()

    # Get or build the workflow
    workflow = job_input.get("workflow")  # Raw API-format workflow JSON

    if not workflow:
        workflow_name = job_input.get("workflow_name", "z-image")

        # Check if we have a built-in builder for this workflow
        builder = WORKFLOW_BUILDERS.get(workflow_name)
        if builder:
            # Use the builder with user-friendly parameters
            build_kwargs = {}
            for key in ("prompt", "seed", "width", "height", "steps",
                        "cfg", "sampler", "scheduler", "denoise"):
                if key in job_input:
                    build_kwargs[key] = job_input[key]
            workflow = builder(**build_kwargs)
        else:
            # Try loading from file (must be API format)
            workflow = load_workflow(workflow_name)
            if not workflow:
                return {"error": f"Workflow '{workflow_name}' not found and no built-in builder"}

    # Apply advanced node-level overrides (for power users)
    overrides = job_input.get("overrides", {})
    if overrides:
        workflow = apply_overrides(workflow, overrides)

    # Execute
    try:
        prompt_id, client_id = queue_workflow(workflow)
        history = wait_for_completion(prompt_id, client_id)
        outputs = collect_outputs(history)

        if not outputs:
            return {"error": "Workflow produced no outputs"}

        # Collect results
        results = []
        return_base64 = job_input.get("return_base64", True)

        for output in outputs:
            result = {
                "type": output["type"],
                "filename": output["filename"],
            }
            if return_base64:
                result["data"] = fetch_output_as_base64(
                    output["filename"],
                    output.get("subfolder", ""),
                    output.get("format", "output"),
                )
            results.append(result)

        return {
            "outputs": results,
            "prompt_id": prompt_id,
            "execution_time": history.get("status", {}).get("execution_time"),
        }

    except ValueError as e:
        return {"error": f"Workflow validation error: {str(e)}"}
    except RuntimeError as e:
        return {"error": f"Execution error: {str(e)}"}
    except Exception as e:
        logger.exception("Unexpected error in handler")
        return {"error": f"Unexpected error: {str(e)}"}


# ── Setup & Entry Point ──────────────────────────────────────────────

def setup():
    """Initialize the A/B manager and start ComfyUI."""
    global ab_manager

    from ab_manager import ABManager

    ab_manager = ABManager(
        volume_path=VOLUME_PATH,
        repo=REPO,
        repo_ref=REPO_REF,
    )

    # Write extra_model_paths.yaml for shared model access
    extra_paths_file = Path(VOLUME_PATH) / "extra_model_paths.yaml"
    if not extra_paths_file.exists():
        extra_paths_content = f"""comfygit_serverless:
  base_path: {VOLUME_PATH}/models
  checkpoints: checkpoints/
  clip: clip/
  clip_vision: clip_vision/
  controlnet: controlnet/
  diffusion_models: diffusion_models/
  embeddings: embeddings/
  loras: loras/
  text_encoders: text_encoders/
  upscale_models: upscale_models/
  vae: vae/
"""
        extra_paths_file.parent.mkdir(parents=True, exist_ok=True)
        extra_paths_file.write_text(extra_paths_content)
        logger.info(f"Wrote {extra_paths_file}")

    # Boot the environment (first boot or warm boot)
    if not ab_manager.boot():
        logger.error("Failed to boot environment — handler will return errors")
        return False

    # Start ComfyUI
    if not start_comfyui():
        logger.error("Failed to start ComfyUI")
        return False

    return True


def main():
    """Entry point — called from start.sh or directly."""
    import runpod

    logger.info("=" * 60)
    logger.info("ComfyGit Serverless Handler Starting")
    logger.info(f"  Repo: {REPO}")
    logger.info(f"  Ref:  {REPO_REF}")
    logger.info(f"  Volume: {VOLUME_PATH}")
    logger.info("=" * 60)

    if not setup():
        logger.error("Setup failed — starting handler anyway (will return errors)")

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
