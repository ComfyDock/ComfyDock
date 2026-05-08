"""Profile a deployed ComfyGit Modal proxy endpoint with a txt2img run."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TOKEN = "modal-proof-token"


def _txt2img_prompt() -> dict[str, Any]:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(time.time() * 1000) % 1_000_000_000,
                "steps": 12,
                "cfg": 8,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "v1-5-pruned-emaonly-fp16.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "beautiful scenery nature glass bottle landscape, purple galaxy bottle",
                "clip": ["4", 1],
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "text, watermark", "clip": ["4", 1]},
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyGit_Modal_Profile", "images": ["8", 0]},
        },
    }


def _request_json(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    body = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {data}") from exc


def _request_bytes(url: str, *, token: str, timeout: float = 60) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("content-type", "application/octet-stream")


def profile_proxy(base_url: str, *, token: str, out_dir: Path, timeout_seconds: float) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    started = time.monotonic()
    health = _request_json("GET", f"{base_url}/proxy/health", token=token, timeout=timeout_seconds)
    timings["health_seconds"] = time.monotonic() - started

    payload = {
        "prompt": _txt2img_prompt(),
        "outputs": [{"name": "save_image", "type": "image", "node_id": "9", "selector": "primary"}],
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": 1,
    }
    submitted_at = time.monotonic()
    submitted = _request_json("POST", f"{base_url}/proxy/runs", token=token, payload=payload, timeout=timeout_seconds)
    timings["submit_seconds"] = time.monotonic() - submitted_at
    prompt_id = str(submitted.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError(f"Proxy did not return prompt_id: {submitted}")

    poll_started = time.monotonic()
    completed: dict[str, Any] = {}
    while time.monotonic() - poll_started < timeout_seconds:
        completed = _request_json(
            "GET",
            f"{base_url}/proxy/runs/{urllib.parse.quote(prompt_id)}",
            token=token,
            timeout=30,
        )
        status = str(completed.get("status") or "").lower()
        if status == "completed":
            break
        if status in {"error", "failed", "cancelled"}:
            raise RuntimeError(f"Run ended with status {status}: {completed}")
        time.sleep(1)
    else:
        raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")
    timings["completion_poll_seconds"] = time.monotonic() - poll_started

    artifacts = [
        artifact
        for output in completed.get("outputs", [])
        if isinstance(output, dict)
        for artifact in output.get("artifacts", [])
        if isinstance(artifact, dict)
    ]
    if not artifacts:
        raise RuntimeError(f"Completed run had no artifacts: {completed}")

    artifact = artifacts[0]
    artifact_url = str(artifact.get("url") or "")
    if artifact_url.startswith("/"):
        artifact_url = f"{base_url}{artifact_url}"

    download_started = time.monotonic()
    artifact_bytes, content_type = _request_bytes(artifact_url, token=token, timeout=timeout_seconds)
    timings["artifact_download_seconds"] = time.monotonic() - download_started
    timings["total_seconds"] = time.monotonic() - started

    suffix = ".png" if "png" in content_type else ".bin"
    output_path = out_dir / f"{prompt_id}{suffix}"
    output_path.write_bytes(artifact_bytes)

    return {
        "health": health,
        "submitted": submitted,
        "completed": completed,
        "artifact": {
            "path": str(output_path),
            "bytes": len(artifact_bytes),
            "content_type": content_type,
            "metadata": artifact,
        },
        "timings": {key: round(value, 3) for key, value in timings.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Deployed Modal proxy URL")
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/comfygit-modal-proxy-profile"))
    parser.add_argument("--timeout-seconds", type=float, default=15 * 60)
    args = parser.parse_args()
    print(
        json.dumps(
            profile_proxy(
                args.base_url,
                token=args.token,
                out_dir=args.out_dir,
                timeout_seconds=args.timeout_seconds,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
