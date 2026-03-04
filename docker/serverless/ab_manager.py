"""
A/B Environment Manager for ComfyGit Serverless

Manages two ComfyGit environments (blue/green) on a persistent network volume.
Handles first-boot setup, environment switching, and update orchestration.
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("ab_manager")

# Environment pair
ENV_NAMES = ("blue", "green")

DEFAULT_STATE = {
    "active_env": "blue",
    "standby_env": "green",
    "initialized": False,
    "last_update": None,
    "last_update_status": None,
    "repo": None,
    "repo_ref": None,
    "boot_count": 0,
}


class ABManager:
    """Manages A/B ComfyGit environments on a network volume."""

    def __init__(
        self,
        volume_path: str = "/runpod-volume",
        repo: str = "",
        repo_ref: str = "main",
    ):
        self.volume_path = Path(volume_path)
        self.repo = repo
        self.repo_ref = repo_ref

        # Paths
        self.workspace_path = self.volume_path / "comfygit-workspace"
        self.models_path = self.volume_path / "models"
        self.state_file = self.volume_path / ".state.json"

        # State
        self._state = self._load_state()

    # ── State Management ──────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Load state from the network volume, or create default."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                logger.info(f"Loaded state: active={state.get('active_env')}, "
                           f"initialized={state.get('initialized')}, "
                           f"boots={state.get('boot_count', 0)}")
                return state
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Corrupt state file, resetting: {e}")
        return dict(DEFAULT_STATE)

    def _save_state(self):
        """Persist state to the network volume."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self._state, f, indent=2)
        logger.debug(f"State saved: {self._state}")

    @property
    def active_env(self) -> str:
        return self._state.get("active_env", "blue")

    @property
    def standby_env(self) -> str:
        return self._state.get("standby_env", "green")

    @property
    def is_initialized(self) -> bool:
        return self._state.get("initialized", False)

    def active_env_path(self) -> Path:
        return self.workspace_path / "environments" / self.active_env

    def standby_env_path(self) -> Path:
        return self.workspace_path / "environments" / self.standby_env

    def active_comfyui_path(self) -> Path:
        return self.active_env_path() / "ComfyUI"

    # ── ComfyGit Commands ─────────────────────────────────────────────

    def _run_cg(self, args: list[str], env_name: str | None = None,
                timeout: int = 600) -> subprocess.CompletedProcess:
        """Run a ComfyGit CLI command."""
        cmd = ["cg"]
        if env_name:
            cmd.extend(["-e", env_name])
        cmd.extend(args)

        env = os.environ.copy()
        env["COMFYGIT_HOME"] = str(self.workspace_path)

        logger.info(f"Running: {' '.join(cmd)}")
        logger.info(f"  COMFYGIT_HOME={env['COMFYGIT_HOME']}")

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.info(f"  [cg] {line}")
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                logger.warning(f"  [cg:err] {line}")

        return result

    # ── Initialization ────────────────────────────────────────────────

    def ensure_directories(self):
        """Create the directory structure on the volume."""
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.models_path.mkdir(parents=True, exist_ok=True)
        for subdir in ["diffusion_models", "text_encoders", "vae",
                       "checkpoints", "clip", "loras", "controlnet",
                       "upscale_models"]:
            (self.models_path / subdir).mkdir(parents=True, exist_ok=True)

    def first_boot(self) -> bool:
        """
        First-time setup: initialize workspace and import the environment.
        Downloads models to the shared volume location.
        Returns True if successful.
        """
        if not self.repo:
            logger.error("COMFYGIT_REPO not set — cannot initialize")
            return False

        logger.info("=" * 60)
        logger.info("FIRST BOOT — Setting up ComfyGit environment")
        logger.info(f"  Repo: {self.repo}")
        logger.info(f"  Ref:  {self.repo_ref}")
        logger.info(f"  Env:  {self.active_env}")
        logger.info("=" * 60)

        self.ensure_directories()

        # Initialize the ComfyGit workspace with models on the network volume.
        # --models-dir ensures model downloads go to persistent storage,
        # not the container's ephemeral disk (typically only 10-20GB).
        result = self._run_cg(
            ["init", "--yes", "--models-dir", str(self.models_path)], timeout=30
        )
        if result.returncode != 0:
            # init may fail if already initialized — that's OK, but ensure
            # models dir is still pointed at the network volume
            logger.warning(f"cg init returned {result.returncode} (may already exist)")
            self._run_cg(
                ["model", "index", "dir", str(self.models_path)], timeout=30
            )

        # Import the environment from the repo
        import_args = [
            "import",
            self.repo,
            "--name", self.active_env,
            "--yes",
            "--no-manager",
            "--models", "all",
        ]
        if self.repo_ref and self.repo_ref != "main":
            import_args.extend(["--branch", self.repo_ref])

        result = self._run_cg(import_args, timeout=1800)  # 30 min for model downloads
        if result.returncode != 0:
            logger.error(f"Environment import failed (exit {result.returncode})")
            return False

        # Verify the environment exists
        comfyui_main = self.active_comfyui_path() / "main.py"
        if not comfyui_main.exists():
            logger.error(f"ComfyUI main.py not found at {comfyui_main}")
            return False

        # Clean up HuggingFace download cache to reclaim volume space.
        # Models are already in the final location; the HF cache holds
        # redundant copies that can double storage usage.
        hf_cache = self.volume_path / ".cache" / "huggingface"
        if hf_cache.exists():
            import shutil
            cache_size = sum(f.stat().st_size for f in hf_cache.rglob("*") if f.is_file())
            shutil.rmtree(hf_cache, ignore_errors=True)
            hf_cache.mkdir(parents=True, exist_ok=True)
            logger.info(f"Cleaned HF cache: freed {cache_size / 1e9:.1f} GB")

        # Update state
        self._state["initialized"] = True
        self._state["repo"] = self.repo
        self._state["repo_ref"] = self.repo_ref
        self._state["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._state["last_update_status"] = "success"
        self._save_state()

        logger.info("First boot complete — environment ready")
        return True

    def warm_boot(self) -> bool:
        """
        Subsequent boot: verify the active environment exists and is usable.
        Returns True if the environment is ready.
        """
        self._state["boot_count"] = self._state.get("boot_count", 0) + 1
        self._save_state()

        comfyui_main = self.active_comfyui_path() / "main.py"
        if not comfyui_main.exists():
            logger.error(f"Active environment missing: {comfyui_main}")
            logger.info("Attempting recovery via first_boot...")
            return self.first_boot()

        logger.info(f"Warm boot #{self._state['boot_count']} — "
                    f"active env: {self.active_env}")
        return True

    def boot(self) -> bool:
        """
        Main boot entry point. Handles first boot vs warm boot.
        Returns True if an environment is ready to serve.
        """
        if self.is_initialized:
            return self.warm_boot()
        else:
            return self.first_boot()

    # ── A/B Update ────────────────────────────────────────────────────

    def update(self) -> dict:
        """
        Update the standby environment, then swap if successful.
        Returns a status dict.
        """
        if not self.is_initialized:
            return {"status": "error", "message": "Not initialized yet"}

        standby = self.standby_env
        standby_path = self.standby_env_path()
        logger.info(f"Updating standby environment: {standby}")

        if standby_path.exists() and (standby_path / "ComfyUI" / "main.py").exists():
            # Environment exists — do a pull (incremental update)
            logger.info(f"Pulling updates into {standby}...")
            result = self._run_cg(["pull"], env_name=standby, timeout=900)
        else:
            # Environment doesn't exist — do a fresh import
            logger.info(f"Importing fresh environment into {standby}...")
            import_args = [
                "import",
                self._state.get("repo", self.repo),
                "--name", standby,
                "--yes",
                "--no-manager",
                "--models", "all",
            ]
            ref = self._state.get("repo_ref", self.repo_ref)
            if ref and ref != "main":
                import_args.extend(["--branch", ref])
            result = self._run_cg(import_args, timeout=1800)

        if result.returncode != 0:
            self._state["last_update_status"] = "failed"
            self._save_state()
            return {
                "status": "error",
                "message": f"Update failed (exit {result.returncode})",
                "stderr": result.stderr[-500:] if result.stderr else "",
                "active_env": self.active_env,
            }

        # Swap active ↔ standby
        old_active = self.active_env
        self._state["active_env"] = standby
        self._state["standby_env"] = old_active
        self._state["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._state["last_update_status"] = "success"
        self._save_state()

        logger.info(f"Update successful — swapped {old_active} → {standby}")
        return {
            "status": "success",
            "message": f"Updated and swapped to {standby}",
            "previous_env": old_active,
            "active_env": standby,
        }

    def status(self) -> dict:
        """Return current state for diagnostics."""
        return {
            "active_env": self.active_env,
            "standby_env": self.standby_env,
            "initialized": self.is_initialized,
            "boot_count": self._state.get("boot_count", 0),
            "last_update": self._state.get("last_update"),
            "last_update_status": self._state.get("last_update_status"),
            "repo": self._state.get("repo", self.repo),
            "repo_ref": self._state.get("repo_ref", self.repo_ref),
            "volume_path": str(self.volume_path),
            "active_env_exists": self.active_comfyui_path().exists(),
            "standby_env_exists": (
                self.standby_env_path() / "ComfyUI" / "main.py"
            ).exists(),
        }
