"""Tests for `cg analyze` command wiring and handler behavior."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from comfygit_cli.cli import create_parser
from comfygit_cli.global_commands import GlobalCommands


def _make_report() -> SimpleNamespace:
    resolution = SimpleNamespace(
        nodes_resolved=[],
        nodes_version_gated=[],
        nodes_uninstallable=[],
        nodes_unresolved=[],
        nodes_ambiguous=[],
        models_resolved=[],
        models_unresolved=[],
        models_ambiguous=[],
    )
    return SimpleNamespace(
        workflow_name="wf",
        input_format="ui_list",
        total_nodes=1,
        total_unique_node_types=1,
        total_model_refs=0,
        builtin_nodes=["KSampler"],
        resolution=resolution,
        models_with_embedded_urls=0,
        models_without_sources=0,
        node_resolution_rate=100.0,
        model_resolution_rate=100.0,
        overall_confidence="high",
        unresolved_items=[],
        draft_spec={"tool": {"comfygit": {}}},
        to_dict=lambda: {"workflow_name": "wf", "overall_confidence": "high"},
    )


def test_parser_registers_analyze_command() -> None:
    parser = create_parser()

    args = parser.parse_args(["analyze", "workflow.json", "--json", "--online"])

    assert args.command == "analyze"
    assert args.workflow == Path("workflow.json")
    assert args.json_output is True
    assert args.draft_spec is False
    assert args.online is True


def test_analyze_uses_standalone_service_when_no_workspace(capsys) -> None:
    global_cmds = GlobalCommands()
    fake_report = _make_report()
    fake_service = Mock()
    fake_service.analyze.return_value = fake_report

    args = argparse.Namespace(
        workflow=Path("workflow.json"),
        json_output=True,
        draft_spec=False,
        online=False,
        verbose=False,
        quiet=False,
    )

    with patch("comfygit_cli.global_commands.get_workspace_optional", return_value=None):
        with patch(
            "comfygit_core.workflow.WorkflowAnalysisService.create_standalone",
            return_value=fake_service,
        ) as create_standalone:
            global_cmds.analyze(args)

    out = capsys.readouterr().out
    assert '"workflow_name": "wf"' in out
    create_standalone.assert_called_once()
    fake_service.analyze.assert_called_once_with(Path("workflow.json"), online=False)


def test_analyze_uses_workspace_service_when_workspace_available(capsys) -> None:
    global_cmds = GlobalCommands()
    fake_report = _make_report()
    fake_service = Mock()
    fake_service.analyze.return_value = fake_report
    fake_workspace = Mock()

    args = argparse.Namespace(
        workflow=Path("workflow.json"),
        json_output=True,
        draft_spec=False,
        online=False,
        verbose=False,
        quiet=False,
    )

    with patch("comfygit_cli.global_commands.get_workspace_optional", return_value=fake_workspace):
        with patch(
            "comfygit_core.workflow.WorkflowAnalysisService.create_from_workspace",
            return_value=fake_service,
        ) as create_from_workspace:
            global_cmds.analyze(args)

    out = capsys.readouterr().out
    assert '"overall_confidence": "high"' in out
    create_from_workspace.assert_called_once_with(fake_workspace)
    fake_service.analyze.assert_called_once_with(Path("workflow.json"), online=False)
