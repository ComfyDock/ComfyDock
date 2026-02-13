#!/usr/bin/env python3
"""
Package management utilities for ComfyGit scripts
"""

import os
import subprocess
import tempfile
from typing import List, Dict, Optional
from utils.base_utils import CommandRunner, Logger


class PackageManager:
    """Base class for package management"""
    
    def __init__(self, use_uv: bool = True):
        self.use_uv = use_uv and CommandRunner.command_exists('uv')
    
    def install_packages(self, packages: List[str], index_url: Optional[str] = None, pre: bool = False) -> None:
        """Install packages using UV or pip"""
        if self.use_uv:
            self._install_with_uv(packages, index_url, pre)
        else:
            self._install_with_pip(packages, index_url, pre)
    
    def install_requirements(self, requirements_file: str) -> None:
        """Install packages from requirements file"""
        if not os.path.exists(requirements_file):
            return
            
        if self.use_uv:
            CommandRunner.run(['uv', 'pip', 'install', '-r', requirements_file])
        else:
            CommandRunner.run(['python', '-m', 'pip', 'install', '-r', requirements_file])
    
    def uninstall_packages(self, packages: List[str]) -> None:
        """Uninstall packages"""
        if not packages:
            return
            
        try:
            if self.use_uv:
                CommandRunner.run(['uv', 'pip', 'uninstall'] + packages + ['-y'], check=False)
            else:
                CommandRunner.run(['python', '-m', 'pip', 'uninstall'] + packages + ['-y'], check=False)
        except subprocess.SubprocessError:
            pass
    
    def _install_with_uv(self, packages: List[str], index_url: Optional[str], pre: bool) -> None:
        """Install packages using UV"""
        cmd = ['uv', 'pip', 'install'] + packages
        
        if index_url:
            cmd.extend(['--index-url', 'https://pypi.org/simple', '--extra-index-url', index_url])
        
        if pre:
            cmd.append('--pre')
        
        CommandRunner.run(cmd)
    
    def _install_with_pip(self, packages: List[str], index_url: Optional[str], pre: bool) -> None:
        """Install packages using pip"""
        cmd = ['python', '-m', 'pip', 'install'] + packages
        
        if index_url:
            cmd.extend(['--index-url', index_url])
        
        if pre:
            cmd.append('--pre')
        
        CommandRunner.run(cmd)


class PyTorchInstaller:
    """Specialized installer for PyTorch packages"""
    
    @staticmethod
    def get_pytorch_index_url(version: str, cuda_version: str) -> str:
        """Get the PyTorch index URL based on version and CUDA"""
        base_url = "https://download.pytorch.org/whl"
        
        if version == "nightly":
            if cuda_version == "cu128":
                return f"{base_url}/nightly/cu128"
            elif cuda_version == "cpu":
                return f"{base_url}/nightly/cpu"
            else:
                return f"{base_url}/nightly/{cuda_version}"
        else:  # stable
            if cuda_version == "cpu":
                return f"{base_url}/cpu"
            else:
                return f"{base_url}/{cuda_version}"
    
    @staticmethod
    def install_pytorch_from_dict(packages_dict: Dict[str, str], 
                                  pytorch_version: str, 
                                  cuda_version: str,
                                  package_manager: PackageManager) -> None:
        """Install PyTorch packages from a dictionary"""
        # Separate main PyTorch packages from others
        main_packages = []
        other_packages = []
        
        for package, version in packages_dict.items():
            if package in ['torch', 'torchvision', 'torchaudio']:
                main_packages.append(f"{package}=={version}")
            else:
                other_packages.append(f"{package}=={version}")
        
        # Get index URL
        index_url = PyTorchInstaller.get_pytorch_index_url(pytorch_version, cuda_version)
        Logger.log(f"Using PyTorch index: {index_url}")
        
        # Uninstall existing PyTorch
        package_manager.uninstall_packages(['torch', 'torchvision', 'torchaudio'])
        
        # Install main packages
        if main_packages:
            # Create temporary requirements file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write('\n'.join(main_packages))
                temp_file = f.name
            
            try:
                if package_manager.use_uv:
                    cmd = ['uv', 'pip', 'install', '--index-url', index_url, '-r', temp_file]
                    if pytorch_version == 'nightly':
                        cmd.append('--pre')
                    CommandRunner.run(cmd)
                else:
                    cmd = ['python', '-m', 'pip', 'install', '--index-url', index_url, '-r', temp_file]
                    if pytorch_version == 'nightly':
                        cmd.append('--pre')
                    CommandRunner.run(cmd)
            finally:
                os.unlink(temp_file)
        
        # Install other packages
        if other_packages:
            package_manager.install_packages(other_packages)