"""
E2E Tests: CLI Smoke Journey
============================
Spec: specs/cli-smoke-journey.yaml
Truth: docs/specs/cli-smoke-validation.md

These tests exercise real ``cg`` commands against disposable workspaces. They
are intentionally broader than unit tests and assert durable state where
possible so refactors do not silently break common CLI flows.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests
import tomlkit

ENV_NAME = "smoke-env"
IMPORTED_ENV_NAME = "imported-smoke"
REGISTRY_SMOKE_NODE = "rgthree-comfy"
REGISTRY_SMOKE_NODE_DIR = "rgthree-comfy"
HEAVY_REGISTRY_NODE = "comfyui-kjnodes"
HEAVY_REGISTRY_NODE_DIR = "ComfyUI-KJNodes"
SIMPLE_WORKFLOW_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "core"
    / "tests"
    / "fixtures"
    / "workflows"
    / "simple_txt2img.json"
)


@dataclass
class CommandRecord:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CliJourney:
    """Small command runner that records a transcript for failed journeys."""

    def __init__(self, root: Path):
        self.root = root
        self.workspace = root / "workspace"
        self.models_a = root / "models-a"
        self.models_b = root / "models-b"
        e2e_root = Path(__file__).resolve().parents[2]
        self.uv_cache = Path(os.environ.get("E2E_UV_CACHE_DIR", e2e_root / ".cache" / "uv"))
        self.external_uv_cache = root / "external-uv-cache"
        self.remote = root / "remote.git"
        self.records: list[CommandRecord] = []
        self.cg_bin = os.environ.get("E2E_CG_BIN", "cg")

        self.uv_cache.mkdir(parents=True, exist_ok=True)
        self.external_uv_cache.mkdir(parents=True, exist_ok=True)
        self.env = os.environ.copy()
        self.env.update(
            {
                "COMFYGIT_HOME": str(self.workspace),
                "UV_CACHE_DIR": str(self.uv_cache),
                "PYTHONUNBUFFERED": "1",
                "GIT_AUTHOR_NAME": "ComfyGit Smoke",
                "GIT_AUTHOR_EMAIL": "smoke@example.invalid",
                "GIT_COMMITTER_NAME": "ComfyGit Smoke",
                "GIT_COMMITTER_EMAIL": "smoke@example.invalid",
            }
        )

    @property
    def env_path(self) -> Path:
        return self.workspace / "environments" / ENV_NAME

    @property
    def imported_env_path(self) -> Path:
        return self.workspace / "environments" / IMPORTED_ENV_NAME

    @property
    def pyproject_path(self) -> Path:
        return self.env_path / ".cec" / "pyproject.toml"

    def run(
        self,
        *args: str | Path,
        check: bool = True,
        timeout: int = 180,
    ) -> subprocess.CompletedProcess[str]:
        string_args = tuple(str(arg) for arg in args)
        cmd = [self.cg_bin, *string_args]
        proc = subprocess.Popen(
            cmd,
            cwd=Path(__file__).resolve().parents[4],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_process(proc, force=True)
            stdout, stderr = proc.communicate(timeout=10)

        result = subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode if proc.returncode is not None else -signal.SIGKILL,
            stdout=stdout,
            stderr=stderr,
        )
        self.records.append(
            CommandRecord(
                args=string_args,
                returncode=result.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        )
        if timed_out:
            transcript = self.write_transcript()
            raise AssertionError(
                f"Command timed out after {timeout}s: {' '.join(cmd)}\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}\n"
                f"transcript: {transcript}"
            )
        if check and result.returncode != 0:
            transcript = self.write_transcript()
            raise AssertionError(
                f"Command failed: {' '.join(cmd)}\n"
                f"exit={result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}\n"
                f"transcript: {transcript}"
            )
        return result

    def git(self, *args: str | Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *[str(arg) for arg in args]],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"Git command failed: git {' '.join(str(arg) for arg in args)}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def write_transcript(self) -> Path:
        transcript = self.root / "cg-smoke-transcript.txt"
        lines: list[str] = []
        for index, record in enumerate(self.records, 1):
            lines.append(f"$ {self.cg_bin} {' '.join(record.args)}")
            lines.append(f"# exit {record.returncode}")
            if record.stdout:
                lines.append("# stdout")
                lines.append(record.stdout.rstrip())
            if record.stderr:
                lines.append("# stderr")
                lines.append(record.stderr.rstrip())
            if index != len(self.records):
                lines.append("")
        transcript.write_text("\n".join(lines) + "\n")
        return transcript

    def manifest(self, env_name: str = ENV_NAME):
        pyproject = self.workspace / "environments" / env_name / ".cec" / "pyproject.toml"
        return tomlkit.parse(pyproject.read_text())


@pytest.fixture
def journey(tmp_path: Path) -> CliJourney:
    runner = CliJourney(tmp_path / "cli-journey")
    runner.root.mkdir(parents=True, exist_ok=True)
    _create_models(runner.models_a, runner.models_b)
    return runner


def _create_models(models_a: Path, models_b: Path) -> None:
    _write_model(models_a / "checkpoints" / "sd15_v1.safetensors", "sd15")
    _write_model(models_a / "checkpoints" / "alpha_model.safetensors", "alpha")
    _write_model(
        models_a / "frame_interpolation" / "film_net_fp16.safetensors",
        "film-net",
    )
    _write_model(models_b / "checkpoints" / "beta_model.safetensors", "beta")


def _write_model(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (f"COMFYGIT_SMOKE_MODEL:{label}\n".encode() * 512)
    path.write_bytes(payload)


def _bootstrap_workspace_and_env(journey: CliJourney) -> None:
    journey.run("init", journey.workspace, "--models-dir", journey.models_a, "--yes")
    journey.run("create", ENV_NAME, "--comfyui", "v0.4.0", "--python", "3.12",
                "--torch-backend", "cpu", "--no-manager", "--use", "--yes", timeout=420)

    workflow_dir = journey.env_path / "ComfyUI" / "user" / "default" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SIMPLE_WORKFLOW_FIXTURE, workflow_dir / "smoke_txt2img.json")


def _assert_manifest_has_model_source(journey: CliJourney, filename: str) -> None:
    config = journey.manifest()
    workflow = config["tool"]["comfygit"]["workflows"]["smoke_txt2img"]
    models = workflow.get("models", [])
    matching = [model for model in models if model.get("filename") == filename]
    assert matching, f"Expected manifest workflow model for {filename}"
    model_hash = matching[0].get("hash")
    assert model_hash, f"Expected manifest workflow model hash for {filename}"
    manifest_model = config["tool"]["comfygit"]["models"][model_hash]
    assert manifest_model.get("sources"), f"Expected source URL for {filename}"


def _set_dependency_group(journey: CliJourney, group: str, packages: list[str]) -> None:
    config = journey.manifest()
    groups = config.setdefault("dependency-groups", tomlkit.table())
    groups[group] = packages
    journey.pyproject_path.write_text(tomlkit.dumps(config))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_comfyui(port: int, timeout: int = 160) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{port}/system_stats", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def _stop_process_group(proc: subprocess.Popen[str]) -> tuple[str, str]:
    if proc.poll() is None:
        _stop_process(proc, force=False)
    try:
        return proc.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        _stop_process(proc, force=True)
        return proc.communicate(timeout=8)


def _stop_process(proc: subprocess.Popen[str], *, force: bool) -> None:
    if os.name == "nt":
        if force:
            proc.kill()
        else:
            proc.terminate()
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def test_cli_local_authoring_journey(journey: CliJourney):
    """
    Spec: cli-smoke-journey.local-authoring-journey
    Clauses: CGSMOKE-CLI-01, CGSMOKE-CLI-02
    """
    journey.run("init", journey.workspace, "--models-dir", journey.models_a, "--yes")

    # Workspace config and tokens are local state and should be reversible.
    show_config = journey.run("config", "--show")
    assert str(journey.workspace) in show_config.stdout
    journey.run("config", "--civitai-key", "smoke-civitai")
    journey.run("config", "--huggingface-token", "smoke-hf")
    journey.run("config", "--github-token", "smoke-gh")
    journey.run("config", "--uv-cache", journey.external_uv_cache)
    configured = journey.run("config", "--show").stdout
    assert "Not set" not in configured
    assert str(journey.external_uv_cache) in configured
    journey.run("config", "--civitai-key", "")
    journey.run("config", "--huggingface-token", "")
    journey.run("config", "--github-token", "")
    journey.run("config", "--uv-cache", "")

    # Model index path, sync, find, and show behavior.
    journey.run("model", "index", "status")
    journey.run("model", "index", "sync")
    assert "alpha_model.safetensors" in journey.run(
        "model", "index", "find", "alpha_model.safetensors"
    ).stdout
    assert "sd15_v1.safetensors" in journey.run(
        "model", "index", "show", "sd15_v1.safetensors"
    ).stdout

    # Environment lifecycle.
    journey.run(
        "create", ENV_NAME,
        "--comfyui", "v0.4.0",
        "--python", "3.12",
        "--torch-backend", "cpu",
        "--no-manager",
        "--use",
        "--yes",
        timeout=420,
    )
    backend_config = (journey.env_path / ".cec" / ".pytorch-backend").read_text()
    assert backend_config.splitlines()[0] == "cpu"
    assert ENV_NAME in journey.run("list").stdout
    journey.run("use", ENV_NAME)
    journey.run("sync", timeout=300)
    assert ENV_NAME in journey.run("status").stdout
    assert "[tool.comfygit" in journey.run("manifest").stdout
    assert "comfyui_version" in journey.run("manifest", "--pretty").stdout
    assert "comfyui_version" in journey.run(
        "manifest", "--section", "tool.comfygit"
    ).stdout
    journey.run("repair", timeout=240)
    journey.run("doctor")

    # Local environment config and dependency group mutation.
    assert "cpu" in journey.run("env-config", "torch-backend", "show").stdout.lower()
    journey.run("env-config", "torch-backend", "set", "cpu")
    journey.run("env-config", "torch-backend", "detect")
    journey.run("env-config", "extras", "add", "smoke-extra")
    assert "smoke-extra" in journey.run("env-config", "extras", "show").stdout
    journey.run("env-config", "extras", "remove", "smoke-extra")
    assert "smoke-extra" not in journey.run("env-config", "extras", "show").stdout

    journey.run("py", "add", "idna", "--group", "smoke-py", timeout=240)
    assert "idna" in journey.run("py", "list", "--all").stdout
    journey.run("py", "remove", "idna", "--group", "smoke-py", timeout=180)
    _set_dependency_group(journey, "smoke-remove-group", ["attrs>=23"])
    journey.run("py", "remove-group", "smoke-remove-group", timeout=180)

    # Saved workflow discovery, resolution, and manual model dependencies.
    workflow_dir = journey.env_path / "ComfyUI" / "user" / "default" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SIMPLE_WORKFLOW_FIXTURE, workflow_dir / "smoke_txt2img.json")
    assert "smoke_txt2img" in journey.run("workflow", "list").stdout
    journey.run("workflow", "resolve", "smoke_txt2img", "--auto", "--no-install", timeout=180)
    assert "smoke_txt2img" in journey.manifest()["tool"]["comfygit"]["workflows"]

    journey.run(
        "model",
        "add-source",
        "sd15_v1.safetensors",
        "https://huggingface.co/comfygit/smoke/resolve/main/sd15_v1.safetensors",
    )
    journey.run(
        "workflow", "model", "add", "smoke_txt2img",
        "--path", "frame_interpolation/film_net_fp16.safetensors",
        "--importance", "required",
    )
    assert "film_net_fp16.safetensors" in journey.run(
        "workflow", "model", "list", "smoke_txt2img"
    ).stdout
    journey.run(
        "model",
        "add-source",
        "film_net_fp16.safetensors",
        "https://huggingface.co/comfygit/smoke/resolve/main/film_net_fp16.safetensors",
    )
    _assert_manifest_has_model_source(journey, "sd15_v1.safetensors")
    _assert_manifest_has_model_source(journey, "film_net_fp16.safetensors")
    journey.run(
        "workflow", "model", "remove", "smoke_txt2img",
        "--path", "frame_interpolation/film_net_fp16.safetensors",
    )
    assert "film_net_fp16.safetensors" not in journey.run(
        "workflow", "model", "list", "smoke_txt2img"
    ).stdout
    journey.run(
        "workflow", "model", "add", "smoke_txt2img",
        "--path", "frame_interpolation/film_net_fp16.safetensors",
        "--importance", "required",
    )
    _assert_manifest_has_model_source(journey, "film_net_fp16.safetensors")

    # Git lifecycle, remotes, export, and import.
    journey.run("commit", "-m", "Smoke workflow dependencies", "--allow-issues", timeout=180)
    assert "Smoke workflow dependencies" in journey.run("log", "-n", "5").stdout
    journey.run("branch", "smoke-branch")
    assert "smoke-branch" in journey.run("branch").stdout
    journey.run("switch", "smoke-branch")
    journey.run("switch", "main")

    journey.git("init", "--bare", journey.remote)
    journey.run("remote", "add", "origin", journey.remote)
    assert "origin" in journey.run("remote", "list").stdout
    journey.run("push", "-r", "origin", timeout=180)
    journey.run("pull", "-r", "origin", "--preview", "--models", "skip", timeout=180)

    export_path = journey.root / "smoke-export.tar.gz"
    journey.run("export", export_path, "--allow-issues", timeout=180)
    assert export_path.exists()
    assert export_path.stat().st_size > 0
    journey.run(
        "import", export_path,
        "--name", IMPORTED_ENV_NAME,
        "--torch-backend", "cpu",
        "--no-manager",
        "--models", "skip",
        "--yes",
        timeout=420,
    )
    assert journey.imported_env_path.exists()
    assert IMPORTED_ENV_NAME in journey.run("-e", IMPORTED_ENV_NAME, "status").stdout

    # Model index stale cleanup after switching model roots.
    journey.run("model", "index", "dir", journey.models_b)
    journey.run("model", "index", "sync")
    assert "beta_model.safetensors" in journey.run(
        "model", "index", "find", "beta_model.safetensors"
    ).stdout
    stale_find = journey.run("model", "index", "find", "alpha_model.safetensors")
    assert "No models found matching: alpha_model.safetensors" in stale_find.stdout

    journey.write_transcript()


@pytest.mark.registry
@pytest.mark.network
def test_cli_registry_node_lifecycle(journey: CliJourney):
    """
    Spec: cli-smoke-journey.registry-node-lifecycle
    Clauses: CGSMOKE-CLI-01, CGSMOKE-CLI-03
    """
    _bootstrap_workspace_and_env(journey)

    registry_update = journey.run("registry", "update", check=False, timeout=180)
    if registry_update.returncode != 0:
        pytest.skip(
            "Registry update failed; skipping network registry smoke. "
            f"stderr: {registry_update.stderr}"
        )
    journey.run("registry", "status")

    journey.run("node", "add", REGISTRY_SMOKE_NODE, timeout=300)
    node_list = journey.run("node", "list").stdout
    assert REGISTRY_SMOKE_NODE in node_list

    manifest = journey.manifest()
    nodes = manifest["tool"]["comfygit"]["nodes"]
    assert REGISTRY_SMOKE_NODE in nodes
    assert (journey.env_path / "ComfyUI" / "custom_nodes" / REGISTRY_SMOKE_NODE_DIR).exists()

    journey.run("sync", timeout=360)
    pyproject_text = journey.pyproject_path.read_text()
    assert REGISTRY_SMOKE_NODE in pyproject_text

    journey.run("node", "remove", REGISTRY_SMOKE_NODE, timeout=180)
    assert "No custom nodes installed" in journey.run("node", "list").stdout
    manifest_after = journey.manifest()
    assert REGISTRY_SMOKE_NODE not in manifest_after["tool"]["comfygit"].get("nodes", {})
    assert not (
        journey.env_path / "ComfyUI" / "custom_nodes" / REGISTRY_SMOKE_NODE_DIR
    ).exists()

    journey.run("sync", timeout=360)
    journey.write_transcript()


@pytest.mark.registry
@pytest.mark.network
@pytest.mark.slow
def test_cli_registry_heavy_kjnodes_add(journey: CliJourney):
    """
    Spec: cli-smoke-journey.heavy-registry-node-add
    Clauses: CGSMOKE-CLI-01, CGSMOKE-CLI-03
    """
    if os.environ.get("E2E_RUN_HEAVY_REGISTRY") != "1":
        pytest.skip("Set E2E_RUN_HEAVY_REGISTRY=1 to run heavyweight registry smoke")

    _bootstrap_workspace_and_env(journey)

    registry_update = journey.run("registry", "update", check=False, timeout=180)
    if registry_update.returncode != 0:
        pytest.skip(
            "Registry update failed; skipping heavyweight registry smoke. "
            f"stderr: {registry_update.stderr}"
        )

    journey.run("node", "add", HEAVY_REGISTRY_NODE, timeout=900)
    assert HEAVY_REGISTRY_NODE in journey.run("node", "list").stdout.lower()

    manifest = journey.manifest()
    nodes = manifest["tool"]["comfygit"]["nodes"]
    assert HEAVY_REGISTRY_NODE in nodes
    assert (journey.env_path / "ComfyUI" / "custom_nodes" / HEAVY_REGISTRY_NODE_DIR).exists()
    journey.write_transcript()


@pytest.mark.slow
def test_cli_run_cpu_launches_comfyui(journey: CliJourney):
    """
    Spec: cli-smoke-journey.cpu-runtime-launch
    Clauses: CGSMOKE-CLI-01, CGSMOKE-CLI-04
    """
    _bootstrap_workspace_and_env(journey)
    port = _free_port()
    cmd = [journey.cg_bin, "run", "--no-sync", "--", "--port", str(port)]
    proc = subprocess.Popen(
        cmd,
        cwd=Path(__file__).resolve().parents[4],
        env=journey.env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    try:
        healthy = _wait_for_comfyui(port)
    finally:
        stdout, stderr = _stop_process_group(proc)

    combined = f"{stdout}\n{stderr}"
    if not healthy:
        transcript = journey.write_transcript()
        raise AssertionError(
            f"ComfyUI did not become healthy on port {port}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}\n"
            f"transcript: {transcript}"
        )

    assert "Arguments: --cpu" in combined or "--cpu --port" in combined
    assert "Starting server" in combined
    assert "IMPORT FAILED" not in combined
    journey.write_transcript()
