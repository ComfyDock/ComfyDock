"""Minimal contract-serving runtime for ComfyGit environments."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from comfygit_core.core.environment import Environment
from comfygit_core.models.workflow_contract import NamedWorkflowContract
from comfygit_core.services.workflow_execution import (
    build_manifest_contract_prompt,
    extract_contract_outputs,
)


@dataclass(frozen=True)
class ServeConfig:
    """Configuration for the local ComfyGit serve adapter."""

    host: str
    port: int
    comfy_url: str


class ComfyUIClient:
    """Small HTTP client for the ComfyUI API used by `cg serve`."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def check_health(self) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}/system_stats", timeout=2)
        response.raise_for_status()
        return response.json()

    def submit_prompt(self, prompt: dict[str, dict[str, Any]]) -> str:
        response = requests.post(
            f"{self.base_url}/prompt",
            json={"prompt": prompt},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return a prompt_id: {payload}")
        return str(prompt_id)

    def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        response = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and prompt_id in payload:
            history = payload[prompt_id]
            return history if isinstance(history, dict) else None
        return payload if isinstance(payload, dict) and payload else None

    def wait_for_history(
        self,
        prompt_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            if history:
                return history
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


class ServeState:
    """Shared immutable-ish state for request handlers."""

    def __init__(self, env: Environment, config: ServeConfig) -> None:
        self.env = env
        self.config = config
        self.client = ComfyUIClient(config.comfy_url)

    def manifest_snapshot(self):
        return self.env.get_manifest_snapshot()


def serve_environment(env: Environment, config: ServeConfig) -> None:
    """Run the local contract-serving HTTP server until interrupted."""

    state = ServeState(env, config)

    class Handler(ContractServeHandler):
        serve_state = state

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    print(f"Serving ComfyGit environment '{env.name}' on http://{config.host}:{config.port}")
    print(f"ComfyUI API target: {config.comfy_url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    finally:
        server.server_close()


class ContractServeHandler(BaseHTTPRequestHandler):
    """HTTP handler for contract-shaped workflow execution."""

    serve_state: ServeState
    server_version = "ComfyGitServe/0.1"

    def do_GET(self) -> None:
        try:
            path_parts = self._path_parts()
            if path_parts == ["health"]:
                self._send_json(HTTPStatus.OK, self._health_payload())
                return
            if path_parts == ["contracts"]:
                self._send_json(HTTPStatus.OK, self._contracts_payload())
                return
            if len(path_parts) == 3 and path_parts[0] == "contracts":
                workflow_name = path_parts[1]
                contract_name = path_parts[2]
                self._send_json(
                    HTTPStatus.OK,
                    self._single_contract_payload(workflow_name, contract_name),
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self) -> None:
        try:
            path_parts = self._path_parts()
            if len(path_parts) == 4 and path_parts[0] == "contracts" and path_parts[3] == "run":
                payload = self._run_contract(path_parts[1], path_parts[2])
                status = (
                    HTTPStatus.BAD_REQUEST
                    if payload.get("status") == "invalid_request"
                    else HTTPStatus.OK
                )
                self._send_json(status, payload)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except requests.RequestException as exc:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "error": "comfyui_unavailable",
                    "message": str(exc),
                    "comfy_url": self.serve_state.config.comfy_url,
                },
            )
        except TimeoutError as exc:
            self._send_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "timeout", "message": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "message": str(exc)})
        except Exception as exc:
            self._send_error(exc)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _path_parts(self) -> list[str]:
        parsed = urlparse(self.path)
        return [unquote(part) for part in parsed.path.strip("/").split("/") if part]

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def _health_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "environment": self.serve_state.env.name,
            "comfy_url": self.serve_state.config.comfy_url,
            "comfyui": {"available": False},
        }
        try:
            self.serve_state.client.check_health()
            payload["comfyui"] = {"available": True}
        except requests.RequestException as exc:
            payload["comfyui"] = {"available": False, "error": str(exc)}
        return payload

    def _contracts_payload(self) -> dict[str, Any]:
        manifest = self.serve_state.manifest_snapshot()
        contracts: list[dict[str, Any]] = []
        for workflow_name, workflow in manifest.workflows.items():
            execution_contract = workflow.execution_contract
            if execution_contract is None:
                continue
            for contract_name, contract in execution_contract.contracts.items():
                contracts.append(
                    self._contract_payload(workflow_name, contract_name, contract)
                )
        return {
            "environment": self.serve_state.env.name,
            "contracts": contracts,
        }

    def _single_contract_payload(self, workflow_name: str, contract_name: str) -> dict[str, Any]:
        manifest = self.serve_state.manifest_snapshot()
        workflow = manifest.workflows.get(workflow_name)
        if workflow is None or workflow.execution_contract is None:
            raise ValueError(f"Workflow '{workflow_name}' does not declare contracts.")
        contract = workflow.execution_contract.contracts.get(contract_name)
        if contract is None:
            raise ValueError(
                f"Workflow '{workflow_name}' does not declare contract '{contract_name}'."
            )
        return self._contract_payload(workflow_name, contract_name, contract)

    def _contract_payload(
        self,
        workflow_name: str,
        contract_name: str,
        contract: NamedWorkflowContract,
    ) -> dict[str, Any]:
        return {
            "workflow": workflow_name,
            "contract": contract_name,
            "display_name": contract.display_name,
            "description": contract.description,
            "inputs": [item.to_dict() for item in contract.inputs],
            "outputs": [item.to_dict() for item in contract.outputs],
        }

    def _run_contract(self, workflow_name: str, contract_name: str) -> dict[str, Any]:
        body = self._read_json_body()
        if "inputs" in body:
            inputs = body["inputs"]
        else:
            control_keys = {"wait", "timeout_seconds", "poll_interval_seconds"}
            inputs = {key: value for key, value in body.items() if key not in control_keys}
        if not isinstance(inputs, dict):
            raise ValueError("'inputs' must be a JSON object.")
        wait = bool(body.get("wait", True))
        timeout_seconds = float(body.get("timeout_seconds", 300))
        poll_interval_seconds = float(body.get("poll_interval_seconds", 1))

        manifest = self.serve_state.manifest_snapshot()
        build_result = build_manifest_contract_prompt(
            manifest,
            self.serve_state.env.cec_path,
            workflow_name,
            inputs,
            contract_name=contract_name,
        )
        if build_result.has_errors:
            return {
                "status": "invalid_request",
                "issues": [asdict(issue) for issue in build_result.issues],
            }

        prompt_id = self.serve_state.client.submit_prompt(build_result.prompt)
        response: dict[str, Any] = {
            "status": "submitted",
            "prompt_id": prompt_id,
            "issues": [asdict(issue) for issue in build_result.issues],
        }
        if not wait:
            return response

        history = self.serve_state.client.wait_for_history(
            prompt_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        outputs = extract_contract_outputs(build_result.outputs, history)
        response.update(
            {
                "status": "completed",
                "outputs": [asdict(output) for output in outputs],
            }
        )
        return response

    def _send_error(self, exc: Exception) -> None:
        self._send_json(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {
                "error": "internal_error",
                "message": str(exc),
            },
        )

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
