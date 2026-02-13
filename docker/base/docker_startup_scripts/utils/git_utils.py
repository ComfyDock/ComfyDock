#!/usr/bin/env python3
"""
Git utilities for ComfyGit scripts
"""

import subprocess
from typing import Optional
from utils.base_utils import CommandRunner, Logger


class GitManager:
    """Handles git operations"""
    
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
    
    def get_current_version(self) -> Optional[str]:
        """Get current git version of repository"""
        try:
            # Try to get tag/version first
            result = CommandRunner.run(
                ['git', 'describe', '--tags', '--always'], 
                cwd=self.repo_path, 
                check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()
            
            # Fall back to commit hash
            result = CommandRunner.run(
                ['git', 'rev-parse', 'HEAD'], 
                cwd=self.repo_path, 
                check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except subprocess.SubprocessError:
            pass
        
        return None
    
    def ref_exists(self, ref: str, ref_type: str) -> bool:
        """Check if a git reference exists"""
        try:
            if ref_type == 'tag':
                result = CommandRunner.run(
                    ['git', 'show-ref', '--verify', '--quiet', f'refs/tags/{ref}'], 
                    cwd=self.repo_path, 
                    check=False
                )
            elif ref_type == 'branch':
                result = CommandRunner.run(
                    ['git', 'show-ref', '--verify', '--quiet', f'refs/remotes/origin/{ref}'], 
                    cwd=self.repo_path, 
                    check=False
                )
            elif ref_type == 'commit':
                result = CommandRunner.run(
                    ['git', 'cat-file', '-e', f'{ref}^{{commit}}'], 
                    cwd=self.repo_path, 
                    check=False
                )
            else:
                return False
            
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False
    
    def checkout_version(self, version: str) -> bool:
        """Checkout a specific version/branch/commit"""
        try:
            # Check if it's a tag
            if self.ref_exists(version, 'tag'):
                Logger.log(f"Checking out tag: {version}")
                CommandRunner.run(['git', 'checkout', f'tags/{version}'], cwd=self.repo_path)
                return True
            
            # Check if it's a branch
            if self.ref_exists(version, 'branch'):
                Logger.log(f"Checking out branch: {version}")
                CommandRunner.run(['git', 'checkout', version], cwd=self.repo_path)
                CommandRunner.run(['git', 'pull', 'origin', version], cwd=self.repo_path, check=False)
                return True
            
            # Check if it's a commit hash
            if self.ref_exists(version, 'commit'):
                Logger.log(f"Checking out commit: {version}")
                CommandRunner.run(['git', 'checkout', version], cwd=self.repo_path)
                return True
            
            return False
        
        except subprocess.SubprocessError:
            return False
    
    def fetch_all(self) -> None:
        """Fetch all branches and tags"""
        CommandRunner.run(['git', 'fetch', '--all', '--tags'], cwd=self.repo_path)
    
    @staticmethod
    def clone(repo_url: str, target_path: str) -> None:
        """Clone a git repository"""
        CommandRunner.run(['git', 'clone', repo_url, target_path])