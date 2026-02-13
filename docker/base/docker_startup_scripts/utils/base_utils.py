#!/usr/bin/env python3
"""
Base utilities for ComfyGit scripts
"""

import os
import subprocess
from typing import List, Optional, Dict, Any
from datetime import datetime


class Logger:
    """Simple logger with consistent formatting"""
    
    @staticmethod
    def log(message: str, prefix: str = ">>") -> None:
        """Print a log message with prefix"""
        print(f"{prefix} {message}", flush=True)
    
    @staticmethod
    def error(message: str) -> None:
        """Print an error message"""
        Logger.log(f"ERROR: {message}", "!!")
    
    @staticmethod
    def warning(message: str) -> None:
        """Print a warning message"""
        Logger.log(f"Warning: {message}", ">>")


class CommandRunner:
    """Handles subprocess execution with consistent error handling"""
    
    @staticmethod
    def run(cmd: List[str], 
            check: bool = True, 
            capture_output: bool = True,
            text: bool = True,
            cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run a command and return the result"""
        return subprocess.run(
            cmd, 
            check=check, 
            capture_output=capture_output,
            text=text,
            cwd=cwd
        )
    
    @staticmethod
    def run_as_user(user: str, cmd: str) -> subprocess.CompletedProcess:
        """Run a command as a specific user"""
        return CommandRunner.run(['su', user, '-c', cmd])
    
    @staticmethod
    def command_exists(command: str) -> bool:
        """Check if a command exists in PATH"""
        try:
            CommandRunner.run(['which', command])
            return True
        except subprocess.CalledProcessError:
            return False


class EnvironmentManager:
    """Manages environment variables and configuration"""
    
    @staticmethod
    def get_container_id() -> str:
        """Get container ID from environment"""
        return os.environ.get('CONTAINER_ID', 'container1')
    
    @staticmethod
    def get_comfyui_directory() -> str:
        """Get ComfyUI directory path"""
        container_id = EnvironmentManager.get_container_id()
        return os.environ.get('COMFYUI_DIRECTORY', f'/env/{container_id}/ComfyUI')
    
    @staticmethod
    def get_comfy_user_info() -> tuple[int, int]:
        """Get the comfy user's UID/GID"""
        wanted_uid = os.environ.get('WANTED_UID', '1000')
        wanted_gid = os.environ.get('WANTED_GID', '1000')
        return int(wanted_uid), int(wanted_gid)
    
    @staticmethod
    def setup_uv_environment(container_id: str) -> Dict[str, str]:
        """Set up UV-specific environment variables"""
        return {
            'UV_LINK_MODE': 'hardlink',
            'UV_COMPILE_BYTECODE': '1',
            'UV_PROJECT_ENVIRONMENT': f'/env/{container_id}/.venv',
            'VIRTUAL_ENV': f'/env/{container_id}/.venv',
            'UV_CACHE_DIR': '/env/uv_cache',
            'UV_PYTHON_INSTALL_DIR': f'/env/uv/python',
            'UV_HTTP_TIMEOUT': '300',
        }


class PathManager:
    """Handles path operations and symlinks"""
    
    @staticmethod
    def ensure_symlink(source: str, target: str) -> None:
        """Create or update a symlink"""
        from pathlib import Path
        
        target_path = Path(target)
        source_path = Path(source)
        
        # Check if symlink needs updating
        if (not target_path.is_symlink() or 
            target_path.resolve() != source_path.resolve()):
            
            Logger.log(f"Creating symlink from {target} to {source}")
            
            # Remove existing symlink or directory
            if target_path.exists() or target_path.is_symlink():
                if target_path.is_dir() and not target_path.is_symlink():
                    import shutil
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            
            # Create new symlink
            target_path.symlink_to(source)
    
    @staticmethod
    def get_owner_string(path: str) -> str:
        """Get owner string for a path"""
        try:
            import stat
            stat_info = os.stat(path)
            return f"{stat_info.st_uid}:{stat_info.st_gid}"
        except (OSError, IOError):
            return "unknown"


# ANSI color codes for colored output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color
    
    @classmethod
    def colorize(cls, text: str, color: str) -> str:
        """Return colored text"""
        return f"{color}{text}{cls.NC}"