"""Shared fixtures for CLI tests."""

import importlib.util
import sys
from pathlib import Path

# Import core test fixtures by adding path and importing from specific module
core_tests_path = Path(__file__).parent.parent.parent / "core" / "tests"
if str(core_tests_path) not in sys.path:
    sys.path.insert(0, str(core_tests_path))

spec = importlib.util.spec_from_file_location("core_conftest", core_tests_path / "conftest.py")
core_conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core_conftest)

# Re-export core fixtures
fixtures_dir = core_conftest.fixtures_dir
workflow_fixtures = core_conftest.workflow_fixtures
model_fixtures = core_conftest.model_fixtures
test_workspace = core_conftest.test_workspace
test_env = core_conftest.test_env
test_models = core_conftest.test_models
simulate_comfyui_save_workflow = core_conftest.simulate_comfyui_save_workflow
load_workflow_fixture = core_conftest.load_workflow_fixture

__all__ = [
    'fixtures_dir',
    'workflow_fixtures',
    'model_fixtures',
    'test_workspace',
    'test_env',
    'test_models',
    'simulate_comfyui_save_workflow',
    'load_workflow_fixture',
]
