#!/usr/bin/env python3
"""
Merge PR and sync branches to prevent divergence.

Usage:
    python merge-and-sync.py [PR_NUMBER]

If PR_NUMBER is not provided, will attempt to find open PR for current branch.
After merging, syncs by pulling main and merging it back into the original branch.
"""

import json
import subprocess
import sys


def run(cmd: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command."""
    print(f"→ {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        print(f"✗ Command failed: {cmd}")
        if result.stderr:
            print(f"  Error: {result.stderr}")
        sys.exit(result.returncode)
    return result


def get_current_branch() -> str:
    """Get the current git branch name."""
    result = run("git branch --show-current", capture=True)
    return result.stdout.strip()


def get_pr_for_branch(branch: str) -> int | None:
    """Get open PR number for a branch."""
    result = run(
        f'gh pr list --head {branch} --state open --json number',
        check=False,
        capture=True
    )
    if result.returncode != 0:
        return None

    prs = json.loads(result.stdout)
    return prs[0]["number"] if prs else None


def get_pr_info(pr_number: int) -> dict:
    """Get PR information."""
    result = run(
        f'gh pr view {pr_number} --json number,title,state,headRefName',
        capture=True
    )
    return json.loads(result.stdout)


def merge_pr(pr_number: int) -> bool:
    """
    Merge a PR into main.
    Returns True if merged, False if already merged.
    """
    pr_info = get_pr_info(pr_number)

    if pr_info["state"] == "MERGED":
        print(f"✓ PR #{pr_number} is already merged")
        return False

    print(f"Merging PR #{pr_number}: {pr_info['title']}")
    result = run(
        f'gh pr merge {pr_number} --merge --delete-branch=false',
        check=False,
        capture=False
    )

    if result.returncode != 0:
        print(f"✗ Failed to merge PR #{pr_number}")
        sys.exit(1)

    print(f"✓ PR #{pr_number} merged successfully")
    return True


def sync_branches(original_branch: str, base_branch: str = "main"):
    """
    Sync branches by pulling base and merging into original branch.
    """
    print(f"\nSyncing {original_branch} with {base_branch}...")

    # Fetch latest
    run(f"git fetch origin {base_branch}")

    # Update local main
    print(f"\nUpdating local {base_branch} branch...")
    run(f"git checkout {base_branch}")
    run(f"git pull origin {base_branch}")

    # Switch back to original branch
    print(f"\nSwitching to {original_branch}...")
    run(f"git checkout {original_branch}")

    # Merge main into original branch
    print(f"\nMerging {base_branch} into {original_branch}...")
    result = run(f"git merge {base_branch}", check=False, capture=False)

    if result.returncode != 0:
        print("✗ Merge conflict detected!")
        print("  Please resolve conflicts manually and run:")
        print("    git merge --continue")
        print(f"    git push origin {original_branch}")
        sys.exit(1)

    # Push synced branch
    print(f"\nPushing synced {original_branch}...")
    run(f"git push origin {original_branch}")

    # Verify sync
    print("\nVerifying branch sync...")
    result = run(f"git log {base_branch}..{original_branch}", capture=True)

    if result.stdout.strip():
        print(f"⚠ Warning: {original_branch} has commits ahead of {base_branch}")
    else:
        print(f"✓ {original_branch} is in sync with {base_branch}")

    print("\n✓ Branch sync complete!")


def main():
    """Main entry point."""
    # Handle help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print(__doc__)
        print("\nUsage examples:")
        print("  # Auto-detect PR from current branch")
        print("  python merge-and-sync.py")
        print("  make merge-and-sync")
        print()
        print("  # Specify PR number explicitly")
        print("  python merge-and-sync.py 13")
        print("  make merge-and-sync PR=13")
        sys.exit(0)

    # Get PR number from args or detect from current branch
    pr_number = None
    if len(sys.argv) > 1:
        try:
            pr_number = int(sys.argv[1])
        except ValueError:
            print(f"✗ Invalid PR number: {sys.argv[1]}")
            print("  Use -h or --help for usage information")
            sys.exit(1)

        # Get branch name from PR
        pr_info = get_pr_info(pr_number)
        original_branch = pr_info["headRefName"]
    else:
        # Use current branch
        original_branch = get_current_branch()

        if original_branch == "main":
            print("✗ Already on main branch. Nothing to sync.")
            sys.exit(1)

        # Try to find PR for current branch
        pr_number = get_pr_for_branch(original_branch)

        if not pr_number:
            print(f"ℹ No open PR found for branch: {original_branch}")
            print("  Skipping merge step, proceeding directly to sync...")
            print()

    print(f"Branch: {original_branch}")
    if pr_number:
        print(f"PR: #{pr_number}")
    else:
        print("PR: None (assuming already merged)")
    print()

    # Merge PR if found
    if pr_number:
        merge_pr(pr_number)
    else:
        print("Skipping PR merge (no open PR found)")

    # Sync branches
    sync_branches(original_branch)

    print(f"\n✅ Done! {original_branch} is synced with main.")


if __name__ == "__main__":
    main()
