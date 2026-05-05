"""Tests for the eval CLI command wrapper."""

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from daita_cli.commands.eval import (
    _reject_cloud_local_options,
    _render_report,
    _resolve_config_path,
)
from daita_cli.main import cli


def test_eval_command_is_registered_without_daita_agents():
    result = CliRunner().invoke(cli, ["eval", "--help"])

    assert result.exit_code == 0
    assert "Run an agent eval suite locally" in result.output
    assert "--record-baseline" in result.output
    assert "--compare-baseline" in result.output
    assert "--local" in result.output
    assert "--cloud" in result.output
    assert "runs" in result.output
    assert "suites" in result.output


def test_eval_runs_subcommand_help_is_reachable():
    result = CliRunner().invoke(cli, ["eval", "runs", "--help"])

    assert result.exit_code == 0
    assert "List cloud eval runs" in result.output
    assert "report" in result.output


def test_eval_suites_subcommand_help_is_reachable():
    result = CliRunner().invoke(cli, ["eval", "suites", "--help"])

    assert result.exit_code == 0
    assert "List registered cloud eval suites" in result.output
    assert "show" in result.output


def test_eval_command_rejects_both_local_and_cloud():
    result = CliRunner().invoke(cli, ["eval", "--local", "--cloud"])

    assert result.exit_code != 0
    assert "Choose either --local or --cloud" in result.output


def test_resolve_config_path_discovers_single_eval_config(tmp_path):
    (tmp_path / "daita-project.yaml").write_text("name: demo\n")
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    config = evals_dir / "sales.yaml"
    config.write_text("name: sales\n")

    assert _resolve_config_path(tmp_path, None) == config


def test_resolve_config_path_requires_explicit_path_for_multiple_configs(tmp_path):
    (tmp_path / "daita-project.yaml").write_text("name: demo\n")
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    (evals_dir / "sales.yaml").write_text("name: sales\n")
    (evals_dir / "support.json").write_text("{}\n")

    with pytest.raises(Exception, match="Multiple eval configs found"):
        _resolve_config_path(tmp_path, None)


def test_render_quiet_report_keeps_ci_output_small():
    report = SimpleNamespace(status="passed", artifact_path=".daita/evals/runs/run-1")

    assert _render_report(report, "pretty", quiet=True, verbose=False) == (
        "PASSED  Output: .daita/evals/runs/run-1"
    )


def test_render_json_accepts_cloud_report_dict():
    report = {"status": "passed", "suite": {"name": "sales"}, "summary": {}}

    assert '"status": "passed"' in _render_report(
        report, "json", quiet=False, verbose=False
    )


def test_cloud_mode_rejects_local_only_options():
    with pytest.raises(Exception, match="local-only options"):
        _reject_cloud_local_options(
            case_ids=("top-products",),
            failed=False,
            runs=None,
            output_dir=None,
            record_baseline=False,
            compare_baseline=False,
            baseline_path=None,
            include_tool_outputs=False,
            no_artifacts=False,
            judge_provider=None,
            judge_model=None,
            judge_api_key=None,
            no_judges=False,
        )
