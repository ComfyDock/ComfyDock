#!/usr/bin/env python3
"""
Python entrypoint script for ComfyGit
"""

import os
import sys
from pathlib import Path
from typing import Dict, Optional

from utils.base_utils import Logger, CommandRunner, EnvironmentManager, PathManager
from utils.permission_utils import OwnershipManager, run_callable_as_user

# Import other installers directly
from check_permissions import ComfyUIPermissionChecker


class ComfyGitEntrypoint:
    """Main entrypoint class for ComfyGit"""
    
    def __init__(self):
        self.env = self._setup_environment()
        os.environ.update(self.env)
    
    def _setup_environment(self) -> Dict[str, str]:
        """Set up environment variables and defaults"""
        env = os.environ.copy()
        
        # Set container ID
        env['CONTAINER_ID'] = EnvironmentManager.get_container_id()
        
        # Set ComfyUI directory
        env['COMFYUI_DIRECTORY'] = EnvironmentManager.get_comfyui_directory()
        
        # Default values
        env['PYTHON_VERSION'] = env.get('PYTHON_VERSION', '3.12')
        env['PYTORCH_CUDA_VERSION'] = env.get('PYTORCH_CUDA_VERSION', 'cu124')
        env['PYTORCH_VERSION'] = env.get('PYTORCH_VERSION', 'stable')
        
        # UV environment variables
        uv_env = EnvironmentManager.setup_uv_environment(env['CONTAINER_ID'])
        env.update(uv_env)
        
        # Set ComfyUI path for install scripts
        env['COMFYUI_PATH'] = env['COMFYUI_DIRECTORY']
        
        env['INSTALL_MANAGER'] = env.get('INSTALL_MANAGER', 'true')
        
        return env
    
    def handle_user_remapping(self) -> None:
        """Handle user remapping if needed"""
        wanted_uid = self.env.get('WANTED_UID')
        wanted_gid = self.env.get('WANTED_GID')
        
        if wanted_uid and wanted_gid:
            self._change_user_ownership(int(wanted_uid), int(wanted_gid))
    
    def _change_user_ownership(self, uid: int, gid: int) -> None:
        """Change user ownership with bind mount detection"""
        Logger.log(f"Re-mapping comfy user to UID={uid} GID={gid}")
        
        # Update user and group
        CommandRunner.run(['usermod', '-o', '-u', str(uid), 'comfy'])
        CommandRunner.run(['groupmod', '-o', '-g', str(gid), 'comfy'])
        
        # Check if we should skip ownership changes
        if os.environ.get('SKIP_OWNERSHIP_FIX') == 'true':
            Logger.log("Skipping ownership changes (SKIP_OWNERSHIP_FIX=true)")
            return
        
        # Only change ownership if ComfyUI symlink exists and points to something
        if os.path.islink('/app/ComfyUI') and os.path.exists('/app/ComfyUI'):
            Logger.log("Changing ownership of /app/ComfyUI (excluding bind mounts)")
            OwnershipManager.change_ownership_recursive('/app/ComfyUI', uid, gid, exclude_mounts=True)
        
        Logger.log("User remapping completed")
    
    def run_permission_check(self) -> None:
        """Run the permission check directly"""
        # Use the permission checker class directly
        checker = ComfyUIPermissionChecker()
        checker.run()
        
        # Check if there are permission issues
        has_issues = (
            os.path.exists('/tmp/problem-files.txt') and os.path.getsize('/tmp/problem-files.txt') > 0
        ) or (
            os.path.exists('/tmp/problem-dirs.txt') and os.path.getsize('/tmp/problem-dirs.txt') > 0
        )
        
        if has_issues:
            Logger.log("⚠️  Permission issues detected!")
            Logger.log("To fix these issues run:")
            Logger.log("  comfygit dev exec (pick running container)")
            Logger.log("  fix-permissions")
            Logger.log("This will show you all affected files and ask for confirmation before making changes.")
        
        # If strict permissions enabled, exit on issues
        if os.environ.get('STRICT_PERMISSIONS') == 'true' and has_issues:
            Logger.error("Permission issues detected and STRICT_PERMISSIONS is enabled")
            Logger.log("Container will not start. Please fix permissions or set STRICT_PERMISSIONS=false")
            sys.exit(1)
        
        Logger.log("Permission check completed")
    
    def handle_permission_checks(self) -> None:
        """Handle permission checks based on configuration"""
        check_mode = os.environ.get('PERMISSION_CHECK_MODE', 'once')
        
        if check_mode == 'never':
            Logger.log("Skipping permission check (PERMISSION_CHECK_MODE=never)")
        elif check_mode == 'once':
            marker_file = '/tmp/.permission-check-done'
            if not os.path.exists(marker_file):
                Logger.log("Running one-time permission check on bind-mounted volumes...")
                self.run_permission_check()
                Path(marker_file).touch()
            else:
                Logger.log("Skipping permission check (already completed once)")
                Logger.log(f"To re-run: delete {marker_file} or set PERMISSION_CHECK_MODE=startup")
        else:  # startup or any other value
            Logger.log("Checking permissions on bind-mounted volumes...")
            self.run_permission_check()
    
    def create_venv(self) -> bool:
        """Create virtual environment if it doesn't exist"""
        venv_path = self.env['VIRTUAL_ENV']
        
        if not os.path.exists(venv_path):
            Logger.log(f"Creating venv in {venv_path} as comfy")
            CommandRunner.run(['su', 'comfy', '-c', f"uv venv {venv_path} --python {self.env['PYTHON_VERSION']}"])
            
            # Create a pip shim module for compatibility with scripts expecting pip
            self._create_pip_shim(venv_path)
        
            return True
        else:
            Logger.log(f"Using existing venv at {venv_path}")
            return False
        
    def _create_pip_shim(self, venv_path: str) -> None:
        """Create a pip module that redirects to UV for compatibility"""
        Logger.log("Creating pip shim for UV compatibility...")
        
        # Find the site-packages directory in the venv
        python_version = self.env['PYTHON_VERSION']
        major_minor = '.'.join(python_version.split('.')[:2])
        site_packages = os.path.join(venv_path, 'lib', f'python{major_minor}', 'site-packages')
        
        # Create pip directory
        pip_dir = os.path.join(site_packages, 'pip')
        os.makedirs(pip_dir, exist_ok=True)
        
        # Create __init__.py
        init_file = os.path.join(pip_dir, '__init__.py')
        with open(init_file, 'w') as f:
            f.write('"""Pip shim for UV compatibility"""\n')
        
        # Create __main__.py that redirects to UV
        main_file = os.path.join(pip_dir, '__main__.py')
        with open(main_file, 'w') as f:
            f.write('''#!/usr/bin/env python3
"""Pip shim that redirects to UV"""
import sys
import subprocess
import os

# Replace 'pip' with 'uv pip' in the command
args = sys.argv[1:]

# Handle special cases
if args and args[0] == 'freeze':
    # UV uses 'uv pip freeze' not 'uv pip list --format=freeze'
    cmd = ['uv', 'pip', 'freeze']
else:
    # For other commands, just pass them through
    cmd = ['uv', 'pip'] + args

# Execute UV command
try:
    result = subprocess.run(cmd, check=False)
    sys.exit(result.returncode)
except Exception as e:
    print(f"Error running UV: {e}", file=sys.stderr)
    sys.exit(1)
''')
        
        # Make sure the files are owned by comfy user
        comfy_uid, comfy_gid = EnvironmentManager.get_comfy_user_info()
        os.chown(pip_dir, comfy_uid, comfy_gid)
        os.chown(init_file, comfy_uid, comfy_gid)
        os.chown(main_file, comfy_uid, comfy_gid)
        
        Logger.log("Pip shim created successfully")
    
    def find_migration_config(self) -> Optional[str]:
        """Find migration config in multiple locations"""
        locations = [
            f"/env/{self.env['CONTAINER_ID']}/comfyui_migration_config.json",
            "/migration/comfyui_migration_config.json"
        ]
        
        for location in locations:
            if os.path.exists(location):
                return location
        return None
    
    def handle_installation(self, first_run: bool) -> None:
        """Handle ComfyUI and dependency installation"""
        Logger.log(f"handle_installation: {first_run}")
        force_reinstall = self.env.get('FORCE_REINSTALL') == 'true'
        install_manager = self.env.get('INSTALL_MANAGER') == 'true'
        Logger.log(f"INSTALL_MANAGER: {install_manager}")
        
        if first_run or force_reinstall:
            Logger.log("First run or forced reinstall detected")
            
            # Check for migration config
            migration_config = self.find_migration_config()
            
            # All installation runs as comfy user
            if migration_config: # TODO: Only perform migration if env variable is set
                Logger.log(f"Found migration config at {migration_config}")
                Logger.log("Installing from migration...")
                
                # Use MigrationInstaller directly as comfy user
                from install_from_migration import MigrationInstaller
                run_callable_as_user('comfy', MigrationInstaller(), 'run', init_kwargs={'install_manager': install_manager})
            else:
                Logger.log("No migration config found, installing defaults...")
                
                comfyui_dir = self.env['COMFYUI_DIRECTORY']
                
                # Check if ComfyUI is already mounted
                if os.path.exists(comfyui_dir) and os.path.exists(os.path.join(comfyui_dir, 'main.py')):
                    Logger.log(f"ComfyUI already mounted at {comfyui_dir}, skipping installation")
                    # Create symlink if needed
                    if not os.path.islink('/app/ComfyUI'):
                        PathManager.ensure_symlink(comfyui_dir, '/app/ComfyUI')
                else:
                    # Install ComfyUI as comfy user
                    from install_comfyui import ComfyUIInstaller
                    run_callable_as_user('comfy', ComfyUIInstaller(), 'run', init_kwargs={'install_manager': install_manager})
                
                # Install PyTorch as comfy user
                from install_pytorch import PyTorchSetup
                run_callable_as_user('comfy', PyTorchSetup(), 'run')
                
                # Install requirements as comfy user
                # self._install_requirements()
                self._install_requirements_as_comfy()

        else:
            Logger.log("Venv already exists, skipping installation")
            
            # Ensure ComfyUI symlink exists
            if not os.path.islink('/app/ComfyUI'):
                comfyui_dir = self.env['COMFYUI_DIRECTORY']
                if os.path.exists(comfyui_dir):
                    PathManager.ensure_symlink(comfyui_dir, '/app/ComfyUI')
    
    def _install_requirements_as_comfy(self):
        """Install requirements as comfy user"""
        code = """
import sys
import os
sys.path.insert(0, '/usr/local/lib/comfygit')
sys.path.insert(0, '/usr/local/bin')

from utils.package_utils import PackageManager
pm = PackageManager()

comfyui_reqs = '/app/ComfyUI/requirements.txt'
if os.path.exists(comfyui_reqs):
    pm.install_requirements(comfyui_reqs)

manager_reqs = '/app/ComfyUI/custom_nodes/ComfyUI-Manager/requirements.txt'
if os.path.exists(manager_reqs):
    pm.install_requirements(manager_reqs)
"""
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        try:
            CommandRunner.run(['su', 'comfy', '-c', f'cd /app && uv run python {temp_file}'])
        finally:
            os.unlink(temp_file)
    
    def run(self) -> None:
        """Main execution method"""
        # Handle user remapping if needed
        self.handle_user_remapping()
        
        # Run permission checks
        self.handle_permission_checks()
        
        # Create venv and handle installation
        first_run = self.create_venv()
        Logger.log(f"Created venv: {first_run}")
        self.handle_installation(first_run)
        
        # Check if we should skip ComfyUI and start shell
        if self.env.get('SKIP_COMFYUI') == 'true':
            Logger.log("Skipping ComfyUI and starting a shell")
            os.execv('/bin/bash', ['/bin/bash'])
        else:
            Logger.log("Switching to user 'comfy'")
            
            # Change to ComfyUI directory
            os.chdir('/app/ComfyUI')
            
            # Get additional arguments
            args = sys.argv[1:]
            
            # Build command
            cmd = [
                'su', 'comfy', '-c', 
                f'umask 000 && uv run python /app/ComfyUI/main.py --listen 0.0.0.0 --port 8188 {" ".join(args)}'
            ]
            
            # Execute ComfyUI
            os.execv('/usr/bin/su', cmd)


def main():
    """Main function"""
    entrypoint = ComfyGitEntrypoint()
    entrypoint.run()


if __name__ == '__main__':
    main()