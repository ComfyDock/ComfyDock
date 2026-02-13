#!/usr/bin/env python3
"""
Permission and mount utilities for ComfyGit scripts
"""

import os
import pwd
import grp
import subprocess
import sys
import stat
from typing import List, Set, Tuple, Callable, Any, Optional, Dict
from utils.base_utils import CommandRunner, Logger


def run_as_user(username: str, func: Callable, *args, **kwargs) -> Any:
    """
    Run a function as a different user using subprocess
    
    This avoids the setuid permission issues by keeping the parent process as root
    and running the function in a subprocess as the target user.
    """
    import pickle
    import base64
    
    # Get the target user's info
    try:
        pw_record = pwd.getpwnam(username)
    except KeyError:
        Logger.error(f"User {username} not found")
        raise
    
    # Prepare the function call
    call_data = {
        'func': func,
        'args': args,
        'kwargs': kwargs,
        'env': dict(os.environ)  # Pass current environment
    }
    
    # Serialize the call
    serialized = base64.b64encode(pickle.dumps(call_data)).decode('utf-8')
    
    # Create the runner code
    runner_code = f"""
import sys
import os
import pickle
import base64

# Restore environment
data = pickle.loads(base64.b64decode('{serialized}'))
os.environ.update(data['env'])

# Set up Python path
sys.path.insert(0, '/usr/local/lib/comfygit')
sys.path.insert(0, '/usr/local/bin')

# Execute the function
result = data['func'](*data['args'], **data['kwargs'])
"""
    
    # Run as the target user
    try:
        result = subprocess.run(
            ['su', username, '-c', f'cd /app && uv run python -c "{runner_code}"'],
            capture_output=False,  # Allow output to flow through
            text=True,
            check=True
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        Logger.error(f"Failed to run as user {username}: {e}")
        raise


def run_callable_as_user(username: str, callable_obj: Any, method_name: str = 'run',
                        init_kwargs: Optional[Dict[str, Any]] = None,
                        method_kwargs: Optional[Dict[str, Any]] = None) -> None:
    """
    Run a callable object (like a class instance) as a different user
    
    This is specifically designed for running installer classes that have a run() method
    
    Args:
        username: Username to run as
        callable_obj: Object instance to get class info from
        method_name: Method name to call (default: 'run')
        init_kwargs: Dictionary of keyword arguments for class constructor
        method_kwargs: Dictionary of keyword arguments for method call
    """
    # Get module and class name
    module_name = callable_obj.__class__.__module__
    class_name = callable_obj.__class__.__name__
    
    # Get the target user's info for permission setting
    try:
        pw_record = pwd.getpwnam(username)
        user_uid = pw_record.pw_uid
        user_gid = pw_record.pw_gid
    except KeyError:
        Logger.error(f"User {username} not found")
        raise
    
    # Prepare initialization arguments
    if init_kwargs is None:
        init_kwargs = {}
    
    # Prepare method arguments
    if method_kwargs is None:
        method_kwargs = {}
    
    # Build the Python code to execute
    code = f"""
import sys
import os

# Set up environment
for key, value in {dict(os.environ)!r}.items():
    os.environ[key] = value

# Set up Python path
sys.path.insert(0, '/usr/local/lib/comfygit')
sys.path.insert(0, '/usr/local/bin')

# Import and run
from {module_name} import {class_name}

# Initialize arguments
init_kwargs = {init_kwargs!r}
method_kwargs = {method_kwargs!r}

# Create instance with init arguments
instance = {class_name}(**init_kwargs)

# Call method with method arguments
instance.{method_name}(**method_kwargs)
"""
    
    # Run as the target user
    temp_file = None
    try:
        # Write to a temporary file to avoid shell escaping issues
        import tempfile
        # Create temp file in a world-readable location
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir='/tmp') as f:
            f.write(code)
            temp_file = f.name
        
        # Make the temp file readable by the target user
        os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        
        # Change ownership to the target user
        os.chown(temp_file, user_uid, user_gid)
        
        # Get critical environment variables for UV
        container_id = os.environ.get('CONTAINER_ID', '')
        uv_env_vars = [
            f"UV_PROJECT_ENVIRONMENT='/env/{container_id}/venv'",
            f"VIRTUAL_ENV='/env/{container_id}/venv'",
            f"UV_CACHE_DIR='/env/uv_cache'",
            f"UV_PYTHON_INSTALL_DIR='/env/{container_id}/uv/python'",
            f"CONTAINER_ID='{container_id}'",
            f"PATH='/bin:/usr/bin:/usr/local/bin:{os.environ.get('PATH', '')}'"
        ]
        env_exports = ' '.join(f'export {var};' for var in uv_env_vars)
        
        result = subprocess.run(
            ['su', username, '-c', f'{env_exports} cd /app && /bin/uv run python {temp_file}'],
            capture_output=False,  # Allow output to flow through
            text=True,
            check=True
        )
    finally:
        if temp_file and os.path.exists(temp_file):
            os.unlink(temp_file)


class MountDetector:
    """Detects bind mounts on the system"""
    
    @staticmethod
    def detect_bind_mounts() -> List[str]:
        """Detect all bind mounts by parsing /proc/self/mountinfo"""
        bind_mounts = []
        
        try:
            with open('/proc/self/mountinfo', 'r') as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 5:
                        mount_point = fields[4]
                        
                        # Skip system mounts
                        system_prefixes = (
                            '/proc/', '/sys/', '/dev/', '/etc/', '/usr/', 
                            '/bin/', '/sbin/', '/lib/', '/lib64/', '/var/', 
                            '/run/', '/tmp/'
                        )
                        
                        if any(mount_point.startswith(prefix) for prefix in system_prefixes):
                            continue
                        
                        # Check if it's in app, home, or env directories
                        target_prefixes = ('/app/', '/home/', '/env/')
                        if any(mount_point.startswith(prefix) for prefix in target_prefixes):
                            bind_mounts.append(mount_point)
        
        except (IOError, OSError):
            pass
        
        return sorted(set(bind_mounts))
    
    @staticmethod
    def detect_bind_mounts_in_path(base_path: str) -> List[str]:
        """Detect bind mounts under a specific path"""
        mount_points = []
        try:
            with open('/proc/self/mountinfo', 'r') as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 5:
                        mount_point = fields[4]
                        # Check if this mount point is under our base path
                        if mount_point.startswith(base_path + '/') or mount_point == base_path:
                            mount_points.append(mount_point)
        except (IOError, OSError):
            pass
        return mount_points


class PermissionChecker:
    """Checks file and directory permissions"""
    
    def __init__(self, uid: int, gid: int):
        self.uid = uid
        self.gid = gid
    
    def can_access_as_comfy(self, path: str) -> bool:
        """Check if comfy user can read and write to a path"""
        try:
            result = CommandRunner.run(
                ['su', 'comfy', '-c', f'test -r "{path}" && test -w "{path}"'],
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False
    
    def check_path_permissions(self, path: str) -> bool:
        """Check if a path has permission issues"""
        try:
            stat_info = os.stat(path)
            file_uid = stat_info.st_uid
            file_gid = stat_info.st_gid
            
            # If already owned by comfy user, no problem
            if file_uid == self.uid and file_gid == self.gid:
                return False
            
            # Test if comfy user can access it
            return not self.can_access_as_comfy(path)
        
        except (OSError, IOError):
            return True  # If we can't stat it, consider it a problem


class OwnershipManager:
    """Manages file ownership operations"""
    
    @staticmethod
    def change_ownership(path: str, uid: int, gid: int) -> bool:
        """Change ownership of a path"""
        try:
            os.chown(path, uid, gid)
            return True
        except OSError:
            return False
    
    @staticmethod
    def change_ownership_recursive(path: str, uid: int, gid: int, exclude_mounts: bool = True) -> None:
        """Change ownership recursively, optionally excluding bind mounts"""
        if exclude_mounts:
            # Detect bind mounts
            bind_mounts = MountDetector.detect_bind_mounts_in_path(path)
            
            if bind_mounts:
                Logger.log("Detected bind mounts (will skip these):")
                for mount in bind_mounts:
                    Logger.log(f"   {mount}")
                
                # Use find with -mount to avoid crossing filesystem boundaries
                try:
                    CommandRunner.run(['find', path, '-mount', '-exec', 'chown', f'{uid}:{gid}', '{}', '+'])
                    Logger.log("Ownership changed for non-bind-mounted files only")
                except subprocess.CalledProcessError:
                    Logger.warning("Some ownership changes failed")
            else:
                Logger.log("No bind mounts detected, changing ownership of entire directory")
                CommandRunner.run(['chown', '-R', f'{uid}:{gid}', path])
        else:
            CommandRunner.run(['chown', '-R', f'{uid}:{gid}', path])