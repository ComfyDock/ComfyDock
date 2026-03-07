"""Translate tunnel commands into local worker actions."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any

from .. import __version__
from ..worker.server import (
    WorkerServer,
    _comfyui_error_detail,
    _create_instance_record,
    _deploy_instance,
    _get_git_log_payload,
    _get_git_status_payload,
    _instance_response,
    _instance_has_git_repo,
    _proxy_comfyui_json_payload,
    _proxy_comfyui_view_payload,
    _start_git_pull,
)


class TunnelHandler:
    """Executes tunnel commands against a local WorkerServer instance."""

    def __init__(self, worker: WorkerServer):
        self.worker = worker

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        message_type = str(message.get("type") or "")
        request_id = str(message.get("request_id") or "")

        if message_type == "health_check":
            return {"type": "health", "request_id": request_id, "payload": self._health_payload()}

        if message_type == "system_info":
            return {"type": "system_info", "request_id": request_id, "payload": self._system_info_payload()}

        if message_type == "list_instances":
            return {"type": "instances", "request_id": request_id, "payload": self._list_instances_payload()}

        if message_type == "get_instance":
            instance_id = str(message.get("instance_id") or "")
            return {"type": "instance", "request_id": request_id, "payload": self._instance_detail_payload(instance_id)}

        if message_type == "git_status":
            instance_id = str(message.get("instance_id") or "")
            payload = await self._git_status(instance_id)
            return {"type": "instance", "request_id": request_id, "payload": payload}

        if message_type == "git_log":
            instance_id = str(message.get("instance_id") or "")
            limit = int(message.get("limit") or 20)
            payload = await self._git_log(instance_id, limit=limit)
            return {"type": "instance", "request_id": request_id, "payload": payload}

        if message_type == "git_pull":
            instance_id = str(message.get("instance_id") or "")
            force = bool(message.get("force", False))
            payload = self._git_pull(instance_id, force=force)
            return {"type": "instance", "request_id": request_id, "payload": payload}

        if message_type == "create_instance":
            payload = message.get("payload")
            if not isinstance(payload, dict):
                raise RuntimeError("Tunnel create_instance payload must be an object.")
            instance = await self._create_instance(payload)
            return {"type": "instance", "request_id": request_id, "payload": instance}

        if message_type == "create_instance_bundle":
            payload = message.get("payload")
            if not isinstance(payload, dict):
                raise RuntimeError("Tunnel create_instance_bundle payload must be an object.")
            instance = await self._create_bundle_instance(payload)
            return {"type": "instance", "request_id": request_id, "payload": instance}

        if message_type == "stop_instance":
            instance_id = str(message.get("instance_id") or "")
            return {"type": "instance", "request_id": request_id, "payload": self._stop_instance(instance_id)}

        if message_type == "start_instance":
            instance_id = str(message.get("instance_id") or "")
            return {"type": "instance", "request_id": request_id, "payload": self._start_instance(instance_id)}

        if message_type == "terminate_instance":
            instance_id = str(message.get("instance_id") or "")
            keep_env = bool(message.get("keep_env", False))
            return {
                "type": "instance",
                "request_id": request_id,
                "payload": self._terminate_instance(instance_id, keep_env=keep_env),
            }

        if message_type == "get_logs":
            instance_id = str(message.get("instance_id") or "")
            lines = int(message.get("lines") or 100)
            return {"type": "logs", "request_id": request_id, "payload": self._logs_payload(instance_id, lines=lines)}

        if message_type == "comfyui_object_info":
            instance_id = str(message.get("instance_id") or "")
            payload = await self._comfyui_object_info(instance_id)
            return {"type": "comfyui", "request_id": request_id, "payload": payload}

        if message_type == "comfyui_prompt":
            instance_id = str(message.get("instance_id") or "")
            payload = message.get("payload")
            if not isinstance(payload, dict):
                raise RuntimeError("Tunnel ComfyUI prompt payload must be an object.")
            response = await self._comfyui_prompt(instance_id, payload)
            return {"type": "comfyui", "request_id": request_id, "payload": response}

        if message_type == "comfyui_history":
            instance_id = str(message.get("instance_id") or "")
            prompt_id = str(message.get("prompt_id") or "")
            response = await self._comfyui_history(instance_id, prompt_id)
            return {"type": "comfyui", "request_id": request_id, "payload": response}

        if message_type == "comfyui_view":
            instance_id = str(message.get("instance_id") or "")
            payload = message.get("payload")
            if not isinstance(payload, dict):
                raise RuntimeError("Tunnel ComfyUI view payload must be an object.")
            response = await self._comfyui_view(instance_id, payload)
            return {"type": "comfyui", "request_id": request_id, "payload": response}

        raise RuntimeError(f"Unsupported tunnel command '{message_type}'.")

    def _health_payload(self) -> dict[str, Any]:
        return {"status": "ok", "worker_version": __version__}

    def _system_info_payload(self) -> dict[str, Any]:
        instances = self.worker.state.instances
        running = sum(1 for instance in instances.values() if instance.status == "running")
        stopped = sum(1 for instance in instances.values() if instance.status == "stopped")

        return {
            "worker_version": __version__,
            "workspace_path": str(self.worker.workspace_path),
            "default_mode": self.worker.default_mode,
            "instances": {
                "total": len(instances),
                "running": running,
                "stopped": stopped,
            },
            "ports": {
                "range_start": self.worker.port_range_start,
                "range_end": self.worker.port_range_end,
                "allocated": list(self.worker.port_allocator.allocated.values()),
                "available": (self.worker.port_range_end - self.worker.port_range_start)
                - len(self.worker.port_allocator.allocated),
            },
        }

    def _list_instances_payload(self) -> dict[str, Any]:
        instances = [
            {
                "id": inst.id,
                "name": inst.name,
                "status": inst.status,
                "mode": inst.mode,
                "assigned_port": inst.assigned_port,
                "comfyui_url": f"http://localhost:{inst.assigned_port}"
                if inst.status == "running"
                else None,
                "created_at": inst.created_at,
            }
            for inst in self.worker.state.instances.values()
        ]
        return {
            "instances": instances,
            "port_range": {
                "start": self.worker.port_range_start,
                "end": self.worker.port_range_end,
            },
            "ports_available": (self.worker.port_range_end - self.worker.port_range_start)
            - len(self.worker.port_allocator.allocated),
        }

    def _instance_detail_payload(self, instance_id: str) -> dict[str, Any]:
        instance = self.worker.state.instances.get(instance_id)
        if not instance:
            raise RuntimeError("Instance not found")

        return {
            "id": instance.id,
            "name": instance.name,
            "environment_name": instance.environment_name,
            "status": instance.status,
            "mode": instance.mode,
            "assigned_port": instance.assigned_port,
            "import_source": instance.import_source,
            "branch": instance.branch,
            "container_id": instance.container_id,
            "pid": instance.pid,
            "created_at": instance.created_at,
            "comfyui_url": f"http://localhost:{instance.assigned_port}"
            if instance.status == "running"
            else None,
        }

    def _instance_for_git(self, instance_id: str):
        instance = self.worker.state.instances.get(instance_id)
        if not instance:
            raise RuntimeError("Instance not found")
        if not _instance_has_git_repo(self.worker, instance):
            raise RuntimeError("No git repository found")
        return instance

    async def _git_status(self, instance_id: str) -> dict[str, Any]:
        instance = self._instance_for_git(instance_id)
        return await _get_git_status_payload(self.worker, instance)

    async def _git_log(self, instance_id: str, *, limit: int) -> dict[str, Any]:
        instance = self._instance_for_git(instance_id)
        return await _get_git_log_payload(
            self.worker,
            instance,
            limit=min(max(int(limit), 1), 100),
        )

    def _git_pull(self, instance_id: str, *, force: bool) -> dict[str, Any]:
        instance = self._instance_for_git(instance_id)
        return _start_git_pull(self.worker, instance, force=force)

    async def _create_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        import_source = payload.get("import_source")
        if not import_source:
            raise RuntimeError("import_source is required")

        name = payload.get("name")
        mode = payload.get("mode", self.worker.default_mode)
        branch = payload.get("branch")

        try:
            instance = _create_instance_record(
                self.worker,
                name=name,
                mode=mode,
                import_source=str(import_source),
                branch=branch,
            )
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc

        asyncio.create_task(_deploy_instance(self.worker, instance))
        return _instance_response(instance)

    async def _create_bundle_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        bundle = payload.get("bundle")
        if not isinstance(bundle, dict):
            raise RuntimeError("bundle payload is required")

        filename = str(bundle.get("filename") or "environment.tar.gz")
        content_b64 = bundle.get("content_b64")
        if not isinstance(content_b64, str) or not content_b64:
            raise RuntimeError("bundle.content_b64 is required")

        try:
            bundle_bytes = base64.b64decode(content_b64.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("bundle.content_b64 is not valid base64 data") from exc

        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
            tmp.write(bundle_bytes)
            bundle_path = Path(tmp.name)

        name = payload.get("name")
        mode = payload.get("mode", self.worker.default_mode)

        try:
            instance = _create_instance_record(
                self.worker,
                name=name,
                mode=mode,
                import_source=f"bundle:{filename}",
                branch=None,
            )
        except RuntimeError as exc:
            try:
                bundle_path.unlink()
            except OSError:
                pass
            raise RuntimeError(str(exc)) from exc

        asyncio.create_task(
            _deploy_instance(
                self.worker,
                instance,
                deploy_source=str(bundle_path),
                cleanup_path=bundle_path,
            )
        )
        return _instance_response(instance)

    def _stop_instance(self, instance_id: str) -> dict[str, Any]:
        instance = self.worker.state.instances.get(instance_id)
        if not instance:
            raise RuntimeError("Instance not found")

        if instance.mode == "native":
            self.worker.native_manager.stop(instance_id, pid=instance.pid)

        self.worker.state.update_status(instance_id, "stopped")
        self.worker.state.save()

        return {
            "id": instance.id,
            "status": "stopped",
            "assigned_port": instance.assigned_port,
            "message": f"Instance stopped. Port {instance.assigned_port} remains reserved.",
        }

    def _start_instance(self, instance_id: str) -> dict[str, Any]:
        instance = self.worker.state.instances.get(instance_id)
        if not instance:
            raise RuntimeError("Instance not found")

        if instance.mode != "native":
            raise RuntimeError("Docker mode is not yet supported")

        proc_info = self.worker.native_manager.start(
            instance_id=instance_id,
            environment_name=instance.environment_name,
            port=instance.assigned_port,
        )
        if not proc_info:
            raise RuntimeError("Failed to start instance")

        self.worker.state.update_status(instance_id, "running", pid=proc_info.pid)
        self.worker.state.save()

        return {
            "id": instance.id,
            "status": "running",
            "assigned_port": instance.assigned_port,
            "comfyui_url": f"http://localhost:{instance.assigned_port}",
            "message": f"Instance started on port {instance.assigned_port}.",
        }

    def _terminate_instance(self, instance_id: str, *, keep_env: bool) -> dict[str, Any]:
        instance = self.worker.state.instances.get(instance_id)
        if not instance:
            raise RuntimeError("Instance not found")

        if instance.mode == "native":
            self.worker.native_manager.terminate(instance_id, pid=instance.pid)
            if not keep_env:
                self.worker.native_manager.delete_environment(instance.environment_name)

        self.worker.port_allocator.release(instance_id)
        self.worker.state.remove_instance(instance_id)
        self.worker.state.save()

        message = f"Instance terminated. Port {instance.assigned_port} released."
        if not keep_env:
            message += f" Environment '{instance.environment_name}' deleted."

        return {
            "id": instance_id,
            "status": "terminated",
            "message": message,
        }

    def _logs_payload(self, instance_id: str, *, lines: int) -> dict[str, Any]:
        instance = self.worker.state.instances.get(instance_id)
        if not instance:
            raise RuntimeError("Instance not found")

        if instance.mode == "native":
            process_logs = self.worker.native_manager.get_logs(instance_id, lines=lines)
            logs = [{"level": "INFO", "message": line} for line in process_logs.stdout]
        else:
            logs = []

        return {"logs": logs}

    async def _comfyui_object_info(self, instance_id: str) -> dict[str, Any]:
        status, payload = await _proxy_comfyui_json_payload(
            self.worker,
            instance_id,
            "GET",
            "/object_info",
        )
        if status >= 400:
            raise RuntimeError(_comfyui_error_detail(status, payload))
        return payload

    async def _comfyui_prompt(
        self,
        instance_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        status, response = await _proxy_comfyui_json_payload(
            self.worker,
            instance_id,
            "POST",
            "/prompt",
            json_body=payload,
        )
        if status >= 400:
            raise RuntimeError(_comfyui_error_detail(status, response))
        return response

    async def _comfyui_history(self, instance_id: str, prompt_id: str) -> dict[str, Any]:
        status, payload = await _proxy_comfyui_json_payload(
            self.worker,
            instance_id,
            "GET",
            f"/history/{prompt_id}",
        )
        if status >= 400:
            raise RuntimeError(_comfyui_error_detail(status, payload))
        return payload

    async def _comfyui_view(
        self,
        instance_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        params = {
            "filename": str(payload.get("filename") or ""),
            "subfolder": str(payload.get("subfolder") or ""),
            "type": str(payload.get("type") or ""),
        }
        status, response = await _proxy_comfyui_view_payload(
            self.worker,
            instance_id,
            params=params,
        )
        if status >= 400:
            raise RuntimeError(_comfyui_error_detail(status, response))
        return response
