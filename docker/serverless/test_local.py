#!/usr/bin/env python3
"""
Local test harness for the ComfyGit Serverless handler.

Runs the handler directly on the host (no Docker, no RunPod SDK needed).
Uses the existing ComfyUI environment on the host for GPU testing.

Usage:
    # Test with existing running ComfyUI instance:
    python test_local.py --comfyui-running

    # Test with auto-start of ComfyUI from the host environment:
    python test_local.py --env-path /data/projects/comfygit-ai/.comfygit-workspace/environments/zimage-api-test

    # Test just the A/B manager (no GPU needed):
    python test_local.py --test-ab-manager
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

# Add the serverless project to path
sys.path.insert(0, str(Path(__file__).parent))


def test_ab_manager():
    """Test the A/B manager logic with a temp directory."""
    import tempfile
    from ab_manager import ABManager

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n{'='*60}")
        print("Testing A/B Manager")
        print(f"{'='*60}")
        print(f"Temp volume: {tmpdir}")

        mgr = ABManager(
            volume_path=tmpdir,
            repo="https://github.com/Akatz-Workflows/Z-Image-Simple.git",
            repo_ref="615a29b",
        )

        # Test state management
        print(f"\n[1] Initial state:")
        status = mgr.status()
        for k, v in status.items():
            print(f"    {k}: {v}")

        assert not mgr.is_initialized
        assert mgr.active_env == "blue"
        assert mgr.standby_env == "green"

        # Test directory creation
        print(f"\n[2] Creating directories...")
        mgr.ensure_directories()
        assert (Path(tmpdir) / "models" / "diffusion_models").exists()
        assert (Path(tmpdir) / "comfygit-workspace").exists()
        print("    ✓ Directories created")

        # Test state persistence
        mgr._state["test_key"] = "test_value"
        mgr._save_state()

        mgr2 = ABManager(volume_path=tmpdir, repo="test", repo_ref="main")
        assert mgr2._state.get("test_key") == "test_value"
        print("    ✓ State persistence works")

        print(f"\n{'='*60}")
        print("A/B Manager tests passed ✓")
        print(f"{'='*60}")


def test_handler_with_running_comfyui(host="127.0.0.1", port=8188):
    """Test the handler against an already-running ComfyUI instance."""
    import requests

    comfy_url = f"http://{host}:{port}"

    # Verify ComfyUI is running
    print(f"\n{'='*60}")
    print(f"Testing handler against ComfyUI at {comfy_url}")
    print(f"{'='*60}")

    try:
        resp = requests.get(f"{comfy_url}/system_stats", timeout=5)
        resp.raise_for_status()
        stats = resp.json()
        print(f"ComfyUI is running:")
        print(f"  VRAM: {stats.get('system', {}).get('vram_total', 0) / 1024**3:.1f} GB")
        print(f"  Devices: {[d.get('name') for d in stats.get('devices', [])]}")
    except Exception as e:
        print(f"ERROR: ComfyUI not reachable at {comfy_url}: {e}")
        print("Start ComfyUI first, or use --env-path to auto-start")
        return False

    # Import handler functions directly
    import handler as h
    h.COMFY_HOST = host
    h.COMFY_PORT = port
    h.COMFY_URL = comfy_url

    # Build the Z-Image workflow using the built-in builder
    test_prompt = "a cyberpunk cat hacker sitting at a computer terminal, neon lights, rain, cinematic"
    test_seed = 12345

    workflow = h.build_zimage_prompt(
        prompt=test_prompt,
        seed=test_seed,
        steps=12,
        width=1024,
        height=1024,
    )

    print(f"\nBuilt z-image workflow ({len(workflow)} nodes)")
    print(f"  prompt: {test_prompt}")
    print(f"  seed: {test_seed}")

    # Execute
    print(f"\nQueuing workflow...")
    start_time = time.time()

    prompt_id, client_id = h.queue_workflow(workflow)
    print(f"  prompt_id: {prompt_id}")
    print(f"  client_id: {client_id}")

    print(f"Waiting for completion...")
    history = h.wait_for_completion(prompt_id, client_id, timeout=120)

    elapsed = time.time() - start_time
    exec_time = history.get("status", {}).get("status_str")
    print(f"  Completed in {elapsed:.1f}s (execution: {history.get('status', {}).get('execution_time', '?')}s)")

    # Collect outputs
    outputs = h.collect_outputs(history)
    print(f"\nOutputs: {len(outputs)}")

    for i, output in enumerate(outputs):
        print(f"  [{i}] {output['type']}: {output['filename']}")

        # Save to disk
        b64_data = h.fetch_output_as_base64(
            output["filename"],
            output.get("subfolder", ""),
            output.get("format", "output"),
        )
        raw = base64.b64decode(b64_data)

        output_dir = Path(os.environ.get("TEST_OUTPUT_DIR", "/tmp/comfygit-serverless-test"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"test_{output['filename']}"
        output_path.write_bytes(raw)
        print(f"  Saved to: {output_path} ({len(raw)/1024:.1f} KB)")

    print(f"\n{'='*60}")
    print(f"Handler test passed ✓ ({elapsed:.1f}s)")
    print(f"{'='*60}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Local test harness for ComfyGit Serverless")
    parser.add_argument("--test-ab-manager", action="store_true",
                       help="Test just the A/B manager logic (no GPU)")
    parser.add_argument("--comfyui-running", action="store_true",
                       help="Test against already-running ComfyUI at localhost:8188")
    parser.add_argument("--host", default="127.0.0.1",
                       help="ComfyUI host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8188,
                       help="ComfyUI port (default: 8188)")
    args = parser.parse_args()

    if args.test_ab_manager:
        test_ab_manager()
    elif args.comfyui_running:
        test_handler_with_running_comfyui(args.host, args.port)
    else:
        # Default: run both
        test_ab_manager()
        print()
        test_handler_with_running_comfyui(args.host, args.port)


if __name__ == "__main__":
    main()
