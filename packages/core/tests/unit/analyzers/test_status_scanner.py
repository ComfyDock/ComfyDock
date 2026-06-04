from comfygit_core.analyzers.status_scanner import _uv_dry_run_reports_changes


def test_uv_dry_run_reports_changes_for_lockfile_and_package_mutations():
    output = """Would use project environment at: C:\\env\\.venv
Resolved 130 packages in 4m 32s
Would update lockfile at: uv.lock
Would download 3 packages
Would uninstall 3 packages
Would install 3 packages
 - torch==2.12.0+cpu
 + torch==2.12.0
"""

    assert _uv_dry_run_reports_changes(output) is True


def test_uv_dry_run_ignores_environment_location_notice():
    output = "Would use project environment at: C:\\env\\.venv\nAudited 87 packages\n"

    assert _uv_dry_run_reports_changes(output) is False
