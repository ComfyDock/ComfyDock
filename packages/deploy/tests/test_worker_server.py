"""Tests for worker HTTP server endpoints.

TDD: Tests written first - should FAIL until implementation exists.
"""

import shutil
import tempfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from comfygit_deploy.worker.server import create_worker_app
from comfygit_deploy.worker.state import InstanceState


class TestWorkerServerEndpoints(AioHTTPTestCase):
    """Test worker server HTTP endpoints."""

    async def get_application(self) -> web.Application:
        """Create test application with temp state directory."""
        # Use temp directory for state files
        self._temp_dir = tempfile.mkdtemp()

        self.test_config = {
            "api_key": "cg_wk_test123",
            "workspace_path": "/tmp/test-workspace",
            "default_mode": "docker",
            "port_range": {"start": 8200, "end": 8210},
        }
        return create_worker_app(
            api_key=self.test_config["api_key"],
            workspace_path=Path(self.test_config["workspace_path"]),
            default_mode=self.test_config["default_mode"],
            port_range_start=8200,
            port_range_end=8210,
            state_dir=Path(self._temp_dir),
        )

    async def tearDownAsync(self) -> None:
        if getattr(self, "_comfyui_runner", None):
            await self._comfyui_runner.cleanup()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    async def _start_comfyui_stub(self) -> tuple[str, int]:
        self._last_prompt_payload = None
        self._last_view_query = None

        stub = web.Application()

        async def object_info(request: web.Request) -> web.Response:
            return web.json_response({"KSampler": {"input": {"required": {}}}})

        async def prompt(request: web.Request) -> web.Response:
            self._last_prompt_payload = await request.json()
            return web.json_response({
                "prompt_id": "prompt-123",
                "received": self._last_prompt_payload,
            })

        async def history(request: web.Request) -> web.Response:
            prompt_id = request.match_info["prompt_id"]
            return web.json_response({prompt_id: {"outputs": {}}})

        async def view(request: web.Request) -> web.Response:
            self._last_view_query = dict(request.query)
            return web.Response(body=b"png-bytes", content_type="image/png")

        stub.router.add_get("/object_info", object_info)
        stub.router.add_post("/prompt", prompt)
        stub.router.add_get("/history/{prompt_id}", history)
        stub.router.add_get("/view", view)

        self._comfyui_runner = web.AppRunner(stub)
        await self._comfyui_runner.setup()
        site = web.TCPSite(self._comfyui_runner, "127.0.0.1", 0)
        await site.start()
        sockets = site._server.sockets
        assert sockets
        return "inst_proxy", sockets[0].getsockname()[1]

    def _register_running_instance(self, instance_id: str, port: int) -> None:
        worker = self.app["worker"]
        worker.state.add_instance(
            InstanceState(
                id=instance_id,
                name="deploy-proxy-test",
                environment_name="deploy-proxy-test",
                mode="native",
                assigned_port=port,
                import_source="https://github.com/test/repo.git",
                status="running",
            )
        )

    @unittest_run_loop
    async def test_health_endpoint_returns_ok(self) -> None:
        """GET /api/v1/health should return 200."""
        resp = await self.client.get(
            "/api/v1/health",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

    @unittest_run_loop
    async def test_health_requires_auth(self) -> None:
        """GET /api/v1/health without auth should return 401."""
        resp = await self.client.get("/api/v1/health")
        assert resp.status == 401

    @unittest_run_loop
    async def test_health_rejects_invalid_key(self) -> None:
        """GET /api/v1/health with wrong key should return 401."""
        resp = await self.client.get(
            "/api/v1/health",
            headers={"Authorization": "Bearer wrong_key"},
        )
        assert resp.status == 401

    @unittest_run_loop
    async def test_system_info_returns_worker_details(self) -> None:
        """GET /api/v1/system/info should return worker system info."""
        resp = await self.client.get(
            "/api/v1/system/info",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert "worker_version" in data
        assert "workspace_path" in data
        assert "default_mode" in data
        assert data["ports"]["range_start"] == 8200
        assert data["ports"]["range_end"] == 8210

    @unittest_run_loop
    async def test_list_instances_returns_empty_initially(self) -> None:
        """GET /api/v1/instances should return empty list initially."""
        resp = await self.client.get(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["instances"] == []

    @unittest_run_loop
    async def test_create_instance_returns_instance_data(self) -> None:
        """POST /api/v1/instances should create and return instance."""
        resp = await self.client.post(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={
                "import_source": "https://github.com/user/env.git",
                "name": "test-deploy",
                "mode": "docker",
            },
        )
        assert resp.status == 201
        data = await resp.json()
        assert "id" in data
        assert data["name"].startswith("deploy-test-deploy")
        # Port should be in valid range (may not be 8200 if that port is in use)
        assert 8200 <= data["assigned_port"] < 8210
        assert data["status"] == "deploying"

    @unittest_run_loop
    async def test_create_instance_validates_import_source(self) -> None:
        """POST /api/v1/instances should require import_source."""
        resp = await self.client.post(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={"name": "test"},
        )
        assert resp.status == 400

    @unittest_run_loop
    async def test_get_instance_returns_details(self) -> None:
        """GET /api/v1/instances/{id} should return instance details."""
        # First create an instance
        create_resp = await self.client.post(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={
                "import_source": "https://github.com/user/env.git",
                "name": "test",
            },
        )
        instance_id = (await create_resp.json())["id"]

        # Then get it
        resp = await self.client.get(
            f"/api/v1/instances/{instance_id}",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["id"] == instance_id

    @unittest_run_loop
    async def test_get_instance_returns_404_for_unknown(self) -> None:
        """GET /api/v1/instances/{id} should return 404 for unknown ID."""
        resp = await self.client.get(
            "/api/v1/instances/nonexistent",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 404

    @unittest_run_loop
    async def test_stop_instance(self) -> None:
        """POST /api/v1/instances/{id}/stop should stop instance."""
        # Create instance
        create_resp = await self.client.post(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={"import_source": "https://github.com/x/y.git"},
        )
        instance_id = (await create_resp.json())["id"]

        # Stop it
        resp = await self.client.post(
            f"/api/v1/instances/{instance_id}/stop",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "stopped"
        assert "assigned_port" in data  # Port preserved

    @unittest_run_loop
    async def test_start_instance(self) -> None:
        """POST /api/v1/instances/{id}/start should start stopped instance."""
        # Create and stop instance in native mode
        create_resp = await self.client.post(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={"import_source": "https://github.com/x/y.git", "mode": "native"},
        )
        instance_id = (await create_resp.json())["id"]
        await self.client.post(
            f"/api/v1/instances/{instance_id}/stop",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )

        # Mock native manager's start method
        worker = self.app["worker"]
        mock_proc_info = type("ProcessInfo", (), {"pid": 12345, "port": 8188})()
        worker.native_manager.start = lambda *args, **kwargs: mock_proc_info

        # Start it
        resp = await self.client.post(
            f"/api/v1/instances/{instance_id}/start",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200

    @unittest_run_loop
    async def test_terminate_instance_releases_port(self) -> None:
        """DELETE /api/v1/instances/{id} should terminate and release port."""
        # Create instance
        create_resp = await self.client.post(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={"import_source": "https://github.com/x/y.git"},
        )
        instance_id = (await create_resp.json())["id"]

        # Terminate it
        resp = await self.client.delete(
            f"/api/v1/instances/{instance_id}",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "terminated"

        # Should be gone from list
        list_resp = await self.client.get(
            "/api/v1/instances",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )
        instances = (await list_resp.json())["instances"]
        assert not any(i["id"] == instance_id for i in instances)

    @unittest_run_loop
    async def test_comfyui_object_info_proxy_returns_json(self) -> None:
        instance_id, port = await self._start_comfyui_stub()
        self._register_running_instance(instance_id, port)

        resp = await self.client.get(
            f"/api/v1/instances/{instance_id}/comfyui/object_info",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )

        assert resp.status == 200
        assert await resp.json() == {"KSampler": {"input": {"required": {}}}}

    @unittest_run_loop
    async def test_comfyui_prompt_proxy_forwards_json_body(self) -> None:
        instance_id, port = await self._start_comfyui_stub()
        self._register_running_instance(instance_id, port)

        resp = await self.client.post(
            f"/api/v1/instances/{instance_id}/comfyui/prompt",
            headers={"Authorization": "Bearer cg_wk_test123"},
            json={"prompt": {"1": {"class_type": "KSampler"}}, "client_id": "run-123"},
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["prompt_id"] == "prompt-123"
        assert self._last_prompt_payload == {
            "prompt": {"1": {"class_type": "KSampler"}},
            "client_id": "run-123",
        }

    @unittest_run_loop
    async def test_comfyui_view_proxy_base64_encodes_binary(self) -> None:
        instance_id, port = await self._start_comfyui_stub()
        self._register_running_instance(instance_id, port)

        resp = await self.client.get(
            f"/api/v1/instances/{instance_id}/comfyui/view"
            "?filename=result.png&subfolder=outputs&type=output",
            headers={"Authorization": "Bearer cg_wk_test123"},
        )

        assert resp.status == 200
        assert await resp.json() == {
            "data": "cG5nLWJ5dGVz",
            "content_type": "image/png",
        }
        assert self._last_view_query == {
            "filename": "result.png",
            "subfolder": "outputs",
            "type": "output",
        }
