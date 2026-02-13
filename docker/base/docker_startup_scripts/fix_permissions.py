#!/usr/bin/env python3
"""
Python script to fix permissions on bind-mounted volumes
"""

import os
import sys
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from utils.base_utils import Logger, EnvironmentManager, Colors, PathManager
from utils.permission_utils import OwnershipManager


class PermissionFixer:
    """Main class for fixing permissions"""
    
    def __init__(self):
        self.check_root()
        self.comfy_uid, self.comfy_gid = EnvironmentManager.get_comfy_user_info()
        self.audit_log = self.setup_audit_log()
    
    def check_root(self) -> None:
        """Check if running as root"""
        if os.geteuid() != 0:
            Logger.log(Colors.colorize("Error: This script must be run as root", Colors.RED))
            Logger.log("Please run: sudo fix-permissions")
            sys.exit(1)
    
    def setup_audit_log(self) -> str:
        """Set up audit logging"""
        audit_dir = Path("/var/log/comfygit")
        audit_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        audit_log = audit_dir / f"permission-fixes-{timestamp}.log"
        
        # Write header
        with open(audit_log, 'w') as f:
            f.write("=== ComfyGit Permission Fix Audit Log ===\n")
            f.write(f"Date: {datetime.now()}\n")
            f.write(f"User: {os.getenv('USER', 'root')}\n")
            f.write(f"Target UID:GID: {self.comfy_uid}:{self.comfy_gid}\n")
            f.write("===========================================\n\n")
        
        return str(audit_log)
    
    def log_change(self, action: str, path: str, old_owner: str, new_owner: str) -> None:
        """Log a permission change"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.audit_log, 'a') as f:
            f.write(f"{timestamp} | {action} | {path} | {old_owner} -> {new_owner}\n")
    
    def run_permission_check(self) -> None:
        """Run the permission check script"""
        # Copy and run the permission check
        shutil.copy('/usr/local/bin/check_permissions.py', '/tmp/check_permissions.py')
        os.chmod('/tmp/check_permissions.py', 0o755)
        
        try:
            with open('/tmp/permission-check-output.txt', 'w') as f:
                import subprocess
                subprocess.run(['/tmp/check_permissions.py'], stdout=f, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            pass
    
    def read_problem_files(self) -> Tuple[List[str], List[str]]:
        """Read problem files and directories"""
        problem_files = []
        problem_dirs = []
        
        # Read problem files
        try:
            with open('/tmp/problem-files.txt', 'r') as f:
                problem_files = [line.strip() for line in f if line.strip()]
        except (OSError, IOError):
            pass
        
        # Read problem directories
        try:
            with open('/tmp/problem-dirs.txt', 'r') as f:  
                problem_dirs = [line.strip() for line in f if line.strip()]
        except (OSError, IOError):
            pass
        
        return problem_files, problem_dirs
    
    def display_issues(self, problem_files: List[str], problem_dirs: List[str]) -> None:
        """Display permission issues found"""
        Logger.log(Colors.colorize("The following items will have their ownership changed to comfy:comfy:", Colors.BLUE))
        print()
        
        if problem_dirs:
            Logger.log(Colors.colorize("Directories:", Colors.YELLOW))
            for directory in problem_dirs:
                if os.path.exists(directory):
                    current_owner = PathManager.get_owner_string(directory)
                    print(f"  📁 {directory} (current: {current_owner})")
            print()
        
        if problem_files:
            Logger.log(Colors.colorize("Files:", Colors.YELLOW))
            # Show up to 20 files, then summarize
            for i, file_path in enumerate(problem_files[:20]):
                if os.path.exists(file_path):
                    current_owner = PathManager.get_owner_string(file_path)
                    print(f"  📄 {file_path} (current: {current_owner})")
            
            if len(problem_files) > 20:
                print(f"  ... and {len(problem_files) - 20} more files")
            print()
    
    def get_user_confirmation(self) -> bool:
        """Get user confirmation to proceed"""
        Logger.log(Colors.colorize("⚠️  WARNING: This will change ownership of the above files and directories!", Colors.RED))
        try:
            response = input("Do you want to proceed? (yes/no): ").strip().lower()
            return response == 'yes'
        except (EOFError, KeyboardInterrupt):
            return False
    
    def fix_directories(self, problem_dirs: List[str]) -> None:
        """Fix directory permissions"""
        if not problem_dirs:
            return
        
        Logger.log("Fixing directories...")
        for directory in problem_dirs:
            if os.path.exists(directory):
                old_owner = PathManager.get_owner_string(directory)
                if OwnershipManager.change_ownership(directory, self.comfy_uid, self.comfy_gid):
                    Logger.log(Colors.colorize(f"  ✓ Fixed: {directory}", Colors.GREEN))
                    self.log_change("DIR", directory, old_owner, f"{self.comfy_uid}:{self.comfy_gid}")
                else:
                    Logger.log(Colors.colorize(f"  ✗ Failed: {directory}", Colors.RED))
                    self.log_change("DIR_FAILED", directory, old_owner, "unchanged")
    
    def fix_files(self, problem_files: List[str]) -> None:
        """Fix file permissions"""
        if not problem_files:
            return
        
        Logger.log("Fixing files...")
        fixed = 0
        failed = 0
        total = len(problem_files)
        
        for file_path in problem_files:
            if os.path.exists(file_path):
                old_owner = PathManager.get_owner_string(file_path)
                if OwnershipManager.change_ownership(file_path, self.comfy_uid, self.comfy_gid):
                    fixed += 1
                    self.log_change("FILE", file_path, old_owner, f"{self.comfy_uid}:{self.comfy_gid}")
                    
                    # Show progress for large file counts
                    if fixed % 100 == 0:
                        Logger.log(Colors.colorize(f"  ✓ Fixed {fixed}/{total} files...", Colors.GREEN))
                else:
                    failed += 1
                    self.log_change("FILE_FAILED", file_path, old_owner, "unchanged")
                    
                    # Show individual failures for first few files
                    if failed <= 10:
                        Logger.log(Colors.colorize(f"  ✗ Failed: {file_path}", Colors.RED))
        
        Logger.log(Colors.colorize(f"  ✓ Fixed {fixed} files", Colors.GREEN))
        if failed > 0:
            Logger.log(Colors.colorize(f"  ✗ Failed to fix {failed} files", Colors.RED))
    
    def add_audit_summary(self) -> None:
        """Add summary to audit log"""
        try:
            with open(self.audit_log, 'r') as f:
                content = f.read()
            
            # Count entries
            dir_fixed = content.count('| DIR |')
            dir_failed = content.count('| DIR_FAILED |')
            file_fixed = content.count('| FILE |')
            file_failed = content.count('| FILE_FAILED |')
            
            with open(self.audit_log, 'a') as f:
                f.write("\n=== Summary ===\n")
                f.write(f"Directories fixed: {dir_fixed}\n")
                f.write(f"Directories failed: {dir_failed}\n")
                f.write(f"Files fixed: {file_fixed}\n")
                f.write(f"Files failed: {file_failed}\n")
                f.write("===============\n")
        
        except (OSError, IOError):
            pass
    
    def verify_fixes(self) -> Tuple[int, int]:
        """Verify the fixes by running permission check again"""
        Logger.log("Verifying permissions...")
        
        try:
            with open('/tmp/permission-check-verify.txt', 'w') as f:
                import subprocess
                subprocess.run(['/tmp/check_permissions.py'], stdout=f, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            pass
        
        # Count remaining issues
        remaining_dirs = 0
        remaining_files = 0
        
        try:
            with open('/tmp/problem-dirs.txt', 'r') as f:
                remaining_dirs = len([line for line in f if line.strip()])
        except (OSError, IOError):
            pass
        
        try:
            with open('/tmp/problem-files.txt', 'r') as f:
                remaining_files = len([line for line in f if line.strip()])
        except (OSError, IOError):
            pass
        
        return remaining_dirs, remaining_files
    
    def cleanup_temp_files(self) -> None:
        """Clean up temporary files"""
        for temp_file in [
            '/tmp/permission-check-output.txt',
            '/tmp/permission-check-verify.txt', 
            '/tmp/initial-problem-files.txt',
            '/tmp/initial-problem-dirs.txt'
        ]:
            try:
                os.remove(temp_file)
            except OSError:
                pass
    
    def run(self) -> None:
        """Main execution method"""
        # Header
        Logger.log(Colors.colorize("=== ComfyGit Permission Fix Tool ===", Colors.BLUE))
        Logger.log(f"This tool will fix permission issues for the comfy user (UID={self.comfy_uid}, GID={self.comfy_gid})")
        print()
        
        # Run permission check
        Logger.log("Checking for permission issues...")
        self.run_permission_check()
        
        # Save initial problem lists
        shutil.copy('/tmp/problem-files.txt', '/tmp/initial-problem-files.txt')
        shutil.copy('/tmp/problem-dirs.txt', '/tmp/initial-problem-dirs.txt')
        
        # Read problem files
        problem_files, problem_dirs = self.read_problem_files()
        
        # Check if there are any issues
        if not problem_files and not problem_dirs:
            Logger.log(Colors.colorize("✅ No permission issues found!", Colors.GREEN))
            Logger.log("All files and directories are accessible by the comfy user.")
            return
        
        # Display issues found
        Logger.log(Colors.colorize("⚠️  Permission issues found:", Colors.YELLOW))
        Logger.log(f"   - Directories: {len(problem_dirs)}")
        Logger.log(f"   - Files: {len(problem_files)}")
        print()
        
        # Show what will be changed
        self.display_issues(problem_files, problem_dirs)
        
        # Get confirmation
        if not self.get_user_confirmation():
            Logger.log("Operation cancelled.")
            return
        
        # Perform fixes
        print()
        Logger.log("Fixing permissions...")
        
        self.fix_directories(problem_dirs)
        self.fix_files(problem_files)
        
        # Add summary to audit log
        self.add_audit_summary()
        
        # Verify fixes
        print()
        remaining_dirs, remaining_files = self.verify_fixes()
        
        if remaining_dirs == 0 and remaining_files == 0:
            Logger.log(Colors.colorize("✅ All permissions successfully fixed!", Colors.GREEN))
        else:
            Logger.log(Colors.colorize("⚠️  Some permission issues remain:", Colors.YELLOW))
            if remaining_dirs > 0:
                Logger.log(f"   - Directories: {remaining_dirs}")
            if remaining_files > 0:
                Logger.log(f"   - Files: {remaining_files}")
            Logger.log("Please check the audit log for details.")
        
        # Show audit log location
        print()
        Logger.log(Colors.colorize(f"📄 Audit log saved to: {self.audit_log}", Colors.BLUE))
        Logger.log("To download the audit log, run:")
        Logger.log(f"  docker cp <container_name>:{self.audit_log} ./permission-fixes.log")
        
        # Cleanup
        self.cleanup_temp_files()


def main():
    """Main function"""
    fixer = PermissionFixer()
    fixer.run()


if __name__ == '__main__':
    main()