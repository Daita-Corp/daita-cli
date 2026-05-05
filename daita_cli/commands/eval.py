"""
daita eval [config] - run local agent evaluation suites.

The command imports daita.evals lazily so cloud-only CLI commands do not require
the agent framework at startup.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Iterable

import click

from daita_cli.api_client import APIError, AuthError, DaitaAPIClient
from daita_cli.eval_cloud import (
    PRODUCTION_ENVIRONMENT,
    build_eval_execute_request,
    cli_source_metadata,
    submit_eval_suite,
    wait_for_eval_report,
)
from daita_cli.output import OutputFormatter
from daita_cli.project_utils import ensure_project_root
from daita_cli.project_utils import load_project_config

_CONFIG_SUFFIXES = {".yaml", ".yml", ".json"}
_FORMAT_CHOICES = ["pretty", "json", "markdown", "junit"]


class EvalGroup(click.Group):
    """Click group that preserves `daita eval <config>` as the default action."""

    def resolve_command(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["__run", *args]
        return super().resolve_command(ctx, args)


def _eval_options(fn):
    options = [
        click.option(
            "--case",
            "case_ids",
            multiple=True,
            help="Run only the named case. May be provided multiple times.",
        ),
        click.option(
            "--failed",
            is_flag=True,
            help="Rerun cases that failed in the latest artifact report for this suite.",
        ),
        click.option("--runs", type=int, help="Override run count for selected cases."),
        click.option(
            "--format",
            "output_format",
            default="pretty",
            show_default=True,
            type=click.Choice(_FORMAT_CHOICES),
            help="Output format.",
        ),
        click.option(
            "--output-dir", type=click.Path(), help="Artifact output directory."
        ),
        click.option(
            "--record-baseline", is_flag=True, help="Record this run as baseline."
        ),
        click.option(
            "--compare-baseline",
            is_flag=True,
            help="Compare this run against the configured or default baseline.",
        ),
        click.option(
            "--baseline", "baseline_path", type=click.Path(), help="Baseline path."
        ),
        click.option(
            "--include-tool-outputs",
            is_flag=True,
            help="Include tool outputs in artifacts and judge inputs.",
        ),
        click.option(
            "--no-artifacts",
            is_flag=True,
            help="Do not write eval artifacts. Intended for ephemeral local runs only.",
        ),
        click.option(
            "--judge-provider", help="Override all configured judge providers."
        ),
        click.option("--judge-model", help="Override all configured judge models."),
        click.option(
            "--judge-api-key",
            help="Override all configured judge API keys. Prefer environment variables.",
        ),
        click.option(
            "--no-judges",
            is_flag=True,
            help="Disable all LLM judge expectations for this run.",
        ),
        click.option(
            "--local", "run_local", is_flag=True, help="Run in the local process."
        ),
        click.option("--cloud", "run_cloud", is_flag=True, help="Run in Daita cloud."),
        click.option("--suite", "suite_name", help="Cloud eval suite name."),
        click.option(
            "--timeout",
            default=900,
            show_default=True,
            type=int,
            help="Timeout seconds.",
        ),
    ]
    for option in reversed(options):
        fn = option(fn)
    return fn


@click.group(
    "eval",
    cls=EvalGroup,
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@_eval_options
@click.pass_context
def eval_command(
    ctx,
    case_ids,
    failed,
    runs,
    output_format,
    output_dir,
    record_baseline,
    compare_baseline,
    baseline_path,
    include_tool_outputs,
    no_artifacts,
    judge_provider,
    judge_model,
    judge_api_key,
    no_judges,
    run_local,
    run_cloud,
    suite_name,
    timeout,
):
    """Run an agent eval suite locally or in Daita cloud."""
    if ctx.invoked_subcommand:
        return
    _execute_eval_invocation(
        ctx=ctx,
        config_path=None,
        case_ids=case_ids,
        failed=failed,
        runs=runs,
        output_format=output_format,
        output_dir=output_dir,
        record_baseline=record_baseline,
        compare_baseline=compare_baseline,
        baseline_path=baseline_path,
        include_tool_outputs=include_tool_outputs,
        no_artifacts=no_artifacts,
        judge_provider=judge_provider,
        judge_model=judge_model,
        judge_api_key=judge_api_key,
        no_judges=no_judges,
        run_local=run_local,
        run_cloud=run_cloud,
        suite_name=suite_name,
        timeout=timeout,
    )


@eval_command.command("__run", hidden=True)
@click.argument("config_path", required=False, type=click.Path())
@_eval_options
@click.pass_context
def eval_default_command(
    ctx,
    config_path,
    case_ids,
    failed,
    runs,
    output_format,
    output_dir,
    record_baseline,
    compare_baseline,
    baseline_path,
    include_tool_outputs,
    no_artifacts,
    judge_provider,
    judge_model,
    judge_api_key,
    no_judges,
    run_local,
    run_cloud,
    suite_name,
    timeout,
):
    """Run an agent eval suite."""
    _execute_eval_invocation(
        ctx=ctx,
        config_path=config_path,
        case_ids=case_ids,
        failed=failed,
        runs=runs,
        output_format=output_format,
        output_dir=output_dir,
        record_baseline=record_baseline,
        compare_baseline=compare_baseline,
        baseline_path=baseline_path,
        include_tool_outputs=include_tool_outputs,
        no_artifacts=no_artifacts,
        judge_provider=judge_provider,
        judge_model=judge_model,
        judge_api_key=judge_api_key,
        no_judges=no_judges,
        run_local=run_local,
        run_cloud=run_cloud,
        suite_name=suite_name,
        timeout=timeout,
    )


def _execute_eval_invocation(
    *,
    ctx,
    config_path,
    case_ids,
    failed,
    runs,
    output_format,
    output_dir,
    record_baseline,
    compare_baseline,
    baseline_path,
    include_tool_outputs,
    no_artifacts,
    judge_provider,
    judge_model,
    judge_api_key,
    no_judges,
    run_local,
    run_cloud,
    suite_name,
    timeout,
):

    obj = ctx.obj or {}
    quiet = bool(obj.get("quiet"))
    verbose = bool(obj.get("verbose"))

    if run_local and run_cloud:
        raise click.ClickException("Choose either --local or --cloud, not both.")
    mode = "cloud" if run_cloud else "local"

    try:
        if mode == "cloud":
            report = asyncio.run(
                _run_cloud_eval(
                    config_path=config_path,
                    suite_name=suite_name,
                    timeout=timeout,
                    case_ids=case_ids,
                    failed=failed,
                    runs=runs,
                    output_dir=output_dir,
                    record_baseline=record_baseline,
                    compare_baseline=compare_baseline,
                    baseline_path=baseline_path,
                    include_tool_outputs=include_tool_outputs,
                    no_artifacts=no_artifacts,
                    judge_provider=judge_provider,
                    judge_model=judge_model,
                    judge_api_key=judge_api_key,
                    no_judges=no_judges,
                    quiet=quiet,
                )
            )
        else:
            report = asyncio.run(
                _run_eval(
                    config_path=config_path,
                    case_ids=case_ids,
                    failed=failed,
                    runs=runs,
                    output_dir=output_dir,
                    write_artifacts=not no_artifacts,
                    compare_baseline=compare_baseline,
                    record_baseline=record_baseline,
                    baseline_path=baseline_path,
                    include_tool_outputs=include_tool_outputs,
                    judge_provider=judge_provider,
                    judge_model=judge_model,
                    judge_api_key=judge_api_key,
                    no_judges=no_judges,
                )
            )
    except AuthError as exc:
        raise click.ClickException(str(exc)) from exc
    except APIError as exc:
        raise click.ClickException(str(exc)) from exc
    except click.ClickException:
        raise
    except KeyboardInterrupt:
        click.echo("\n  Eval cancelled.", err=True)
        sys.exit(130)
    except ImportError as exc:
        raise click.ClickException(
            "daita eval requires daita-agents with eval support.\n"
            "Install or upgrade with: pip install -U daita-agents"
        ) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    rendered = _render_report(report, output_format, quiet=quiet, verbose=verbose)
    if rendered:
        click.echo(rendered)

    sys.exit(0 if _report_status(report) == "passed" else 1)


@eval_command.group("runs", invoke_without_command=True)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--suite", "eval_suite_id", help="Filter by eval suite ID.")
@click.option("--project", "project_name", help="Filter by project name.")
@click.option("--status", "status_filter", help="Filter by run status.")
@click.pass_context
def runs_group(ctx, limit, eval_suite_id, project_name, status_filter):
    """List cloud eval runs."""
    if ctx.invoked_subcommand:
        return
    _run_api_command(
        ctx,
        _list_eval_runs(
            formatter=(ctx.obj or {}).get("formatter", OutputFormatter()),
            limit=limit,
            eval_suite_id=eval_suite_id,
            project_name=project_name,
            status_filter=status_filter,
        ),
    )


@runs_group.command("show")
@click.argument("eval_run_id")
@click.pass_context
def show_eval_run(ctx, eval_run_id):
    """Show one cloud eval run."""
    _run_api_command(
        ctx,
        _show_eval_run(
            eval_run_id,
            formatter=(ctx.obj or {}).get("formatter", OutputFormatter()),
        ),
    )


@runs_group.command("report")
@click.argument("eval_run_id")
@click.option(
    "--format",
    "output_format",
    default="pretty",
    show_default=True,
    type=click.Choice(_FORMAT_CHOICES),
)
@click.pass_context
def show_eval_report(ctx, eval_run_id, output_format):
    """Print the canonical report for a cloud eval run."""
    _run_api_command(ctx, _show_eval_report(eval_run_id, output_format))


@eval_command.group("suites", invoke_without_command=True)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--project", "project_name", help="Filter by project name.")
@click.option("--agent", "agent_name", help="Filter by agent name.")
@click.option("--status", "status_filter", help="Filter by suite status.")
@click.pass_context
def suites_group(ctx, limit, project_name, agent_name, status_filter):
    """List registered cloud eval suites."""
    if ctx.invoked_subcommand:
        return
    _run_api_command(
        ctx,
        _list_eval_suites(
            formatter=(ctx.obj or {}).get("formatter", OutputFormatter()),
            limit=limit,
            project_name=project_name,
            agent_name=agent_name,
            status_filter=status_filter,
        ),
    )


@suites_group.command("show")
@click.argument("eval_suite_id")
@click.pass_context
def show_eval_suite(ctx, eval_suite_id):
    """Show one registered cloud eval suite."""
    _run_api_command(
        ctx,
        _show_eval_suite(
            eval_suite_id,
            formatter=(ctx.obj or {}).get("formatter", OutputFormatter()),
        ),
    )


def _run_api_command(ctx, coro) -> None:
    formatter = (ctx.obj or {}).get("formatter", OutputFormatter())
    try:
        asyncio.run(coro)
    except AuthError as exc:
        formatter.error("AUTH_ERROR", str(exc))
        sys.exit(2)
    except APIError as exc:
        formatter.error("API_ERROR", str(exc), {"status_code": exc.status_code})
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except click.ClickException:
        raise
    except Exception as exc:
        formatter.error("ERROR", str(exc))
        sys.exit(1)


async def _list_eval_runs(
    *,
    formatter: OutputFormatter,
    limit: int,
    eval_suite_id: str | None,
    project_name: str | None,
    status_filter: str | None,
) -> None:
    params = {"per_page": limit, "environment": PRODUCTION_ENVIRONMENT}
    if eval_suite_id:
        params["eval_suite_id"] = eval_suite_id
    if project_name:
        params["project_name"] = project_name
    if status_filter:
        params["status"] = status_filter

    async with DaitaAPIClient() as client:
        data = await client.get("/api/v1/evals/runs", params=params)

    rows = [_eval_run_row(item) for item in data.get("runs", [])]
    formatter.list_items(
        rows,
        ["id", "suite", "status", "score", "project", "created"],
        title="Cloud Eval Runs",
    )


async def _show_eval_run(eval_run_id: str, *, formatter: OutputFormatter) -> None:
    async with DaitaAPIClient() as client:
        data = await client.get(f"/api/v1/evals/runs/{eval_run_id}")
    formatter.item(_eval_run_row(data, include_details=True))


async def _show_eval_report(eval_run_id: str, output_format: str) -> None:
    async with DaitaAPIClient() as client:
        report = await client.get(f"/api/v1/evals/runs/{eval_run_id}/report")
    click.echo(
        _render_report(
            _coerce_report(report), output_format, quiet=False, verbose=False
        )
    )


async def _list_eval_suites(
    *,
    formatter: OutputFormatter,
    limit: int,
    project_name: str | None,
    agent_name: str | None,
    status_filter: str | None,
) -> None:
    params = {"per_page": limit, "environment": PRODUCTION_ENVIRONMENT}
    if project_name:
        params["project_name"] = project_name
    if agent_name:
        params["agent_name"] = agent_name
    if status_filter:
        params["status"] = status_filter

    async with DaitaAPIClient() as client:
        data = await client.get("/api/v1/evals/suites", params=params)

    rows = [_eval_suite_row(item) for item in data.get("suites", [])]
    formatter.list_items(
        rows,
        ["id", "name", "project", "agent", "status", "updated"],
        title="Cloud Eval Suites",
    )


async def _show_eval_suite(eval_suite_id: str, *, formatter: OutputFormatter) -> None:
    async with DaitaAPIClient() as client:
        data = await client.get(f"/api/v1/evals/suites/{eval_suite_id}")
    formatter.item(_eval_suite_row(data, include_details=True))


def _eval_run_row(item: dict, *, include_details: bool = False) -> dict:
    row = {
        "id": item.get("eval_run_id"),
        "suite": item.get("suite_name"),
        "status": item.get("status"),
        "score": _format_score(item.get("score")),
        "project": item.get("project_name"),
        "created": _short_time(item.get("created_at")),
    }
    if include_details:
        row.update(
            {
                "environment": item.get("environment"),
                "config_path": item.get("config_path"),
                "report_run_id": item.get("report_run_id"),
                "artifact_s3_bucket": item.get("artifact_s3_bucket"),
                "artifact_s3_prefix": item.get("artifact_s3_prefix"),
                "completed_at": item.get("completed_at"),
            }
        )
    return row


def _eval_suite_row(item: dict, *, include_details: bool = False) -> dict:
    row = {
        "id": item.get("eval_suite_id"),
        "name": item.get("name"),
        "project": item.get("project_name"),
        "agent": item.get("agent_name") or item.get("workflow_name") or "",
        "status": item.get("status"),
        "updated": _short_time(item.get("updated_at")),
    }
    if include_details:
        row.update(
            {
                "environment": item.get("environment"),
                "deployment_id": item.get("deployment_id"),
                "version": item.get("version"),
                "config_path": item.get("config_path"),
                "config_hash": item.get("config_hash"),
                "created_at": item.get("created_at"),
            }
        )
    return row


def _format_score(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _short_time(value) -> str:
    if not value:
        return ""
    return str(value).replace("T", " ")[:19]


async def _run_eval(
    *,
    config_path: str | None,
    case_ids: Iterable[str],
    failed: bool,
    runs: int | None,
    output_dir: str | None,
    write_artifacts: bool,
    compare_baseline: bool,
    record_baseline: bool,
    baseline_path: str | None,
    include_tool_outputs: bool,
    judge_provider: str | None,
    judge_model: str | None,
    judge_api_key: str | None,
    no_judges: bool,
):
    project_root = ensure_project_root()
    _add_project_to_path(project_root)

    from daita.evals import EvalSuite

    config_file = _resolve_config_path(project_root, config_path)
    suite = EvalSuite.from_file(config_file)
    suite.config = suite.config.model_copy(deep=True)
    suite.config_path = str(config_file)

    selected_cases = set(case_ids or [])
    if failed:
        selected_cases.update(_latest_failed_cases(project_root, suite.config))
        if not selected_cases:
            raise click.ClickException(
                "No failed cases found in the latest eval report for this suite."
            )

    if selected_cases:
        _filter_cases(suite.config, config_file, selected_cases)

    if runs is not None:
        if runs < 1:
            raise click.ClickException("--runs must be greater than zero.")
        _override_runs(suite.config, runs)

    if include_tool_outputs:
        _include_tool_outputs(suite.config)

    if no_judges:
        _disable_judges(suite.config)
    elif judge_provider or judge_model or judge_api_key:
        _override_judges(
            suite.config,
            provider=judge_provider,
            model=judge_model,
            api_key=judge_api_key,
        )

    resolved_output_dir = _resolve_optional_path(project_root, output_dir)
    resolved_baseline = _resolve_optional_path(project_root, baseline_path)

    return await suite.run(
        output_dir=resolved_output_dir,
        write_artifacts=write_artifacts,
        compare_baseline=compare_baseline,
        record_baseline=record_baseline,
        baseline_path=resolved_baseline,
    )


async def _run_cloud_eval(
    *,
    config_path: str | None,
    suite_name: str | None,
    timeout: int,
    case_ids: Iterable[str],
    failed: bool,
    runs: int | None,
    output_dir: str | None,
    record_baseline: bool,
    compare_baseline: bool,
    baseline_path: str | None,
    include_tool_outputs: bool,
    no_artifacts: bool,
    judge_provider: str | None,
    judge_model: str | None,
    judge_api_key: str | None,
    no_judges: bool,
    quiet: bool,
):
    _reject_cloud_local_options(
        case_ids=case_ids,
        failed=failed,
        runs=runs,
        output_dir=output_dir,
        record_baseline=record_baseline,
        compare_baseline=compare_baseline,
        baseline_path=baseline_path,
        include_tool_outputs=include_tool_outputs,
        no_artifacts=no_artifacts,
        judge_provider=judge_provider,
        judge_model=judge_model,
        judge_api_key=judge_api_key,
        no_judges=no_judges,
    )

    project_root = ensure_project_root()
    project_config = load_project_config(project_root) or {}
    project_name = project_config.get("name") or project_root.name
    resolved_config = _resolve_cloud_config_path(project_root, config_path)

    request = {
        "project_name": project_name,
        **build_eval_execute_request(
            timeout_seconds=timeout,
            trigger_source="cli",
            source_metadata=cli_source_metadata("daita eval --cloud"),
            suite_name=suite_name,
            config_path=resolved_config,
        ),
    }

    async with DaitaAPIClient() as client:
        if not quiet:
            target = suite_name or resolved_config or "latest eval suite"
            click.echo(f"  Submitting cloud eval: {target}")
        submitted = await submit_eval_suite(client, request)
        report = await _wait_for_cloud_eval_report(
            client=client,
            submitted=submitted,
            timeout=timeout,
            quiet=quiet,
        )
        return _coerce_report(report)


def _resolve_config_path(project_root: Path, config_path: str | None) -> Path:
    if config_path:
        path = Path(config_path)
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            raise click.ClickException(f"Eval config not found: {path}")
        return path

    evals_dir = project_root / "evals"
    candidates = sorted(
        path
        for path in evals_dir.glob("*")
        if path.is_file() and path.suffix.lower() in _CONFIG_SUFFIXES
    )
    if not candidates:
        raise click.ClickException(
            "No eval config found. Add one under evals/ or pass a config path."
        )
    if len(candidates) > 1:
        names = ", ".join(str(path.relative_to(project_root)) for path in candidates)
        raise click.ClickException(
            f"Multiple eval configs found ({names}). Pass the config path explicitly."
        )
    return candidates[0]


def _resolve_cloud_config_path(
    project_root: Path, config_path: str | None
) -> str | None:
    if not config_path:
        return None
    path = Path(config_path)
    if path.is_absolute():
        try:
            return str(path.relative_to(project_root))
        except ValueError:
            raise click.ClickException("Cloud eval config must be inside the project.")
    return str(path)


def _reject_cloud_local_options(
    *,
    case_ids: Iterable[str],
    failed: bool,
    runs: int | None,
    output_dir: str | None,
    record_baseline: bool,
    compare_baseline: bool,
    baseline_path: str | None,
    include_tool_outputs: bool,
    no_artifacts: bool,
    judge_provider: str | None,
    judge_model: str | None,
    judge_api_key: str | None,
    no_judges: bool,
) -> None:
    unsupported = []
    if tuple(case_ids or ()):
        unsupported.append("--case")
    if failed:
        unsupported.append("--failed")
    if runs is not None:
        unsupported.append("--runs")
    if output_dir:
        unsupported.append("--output-dir")
    if record_baseline:
        unsupported.append("--record-baseline")
    if compare_baseline:
        unsupported.append("--compare-baseline")
    if baseline_path:
        unsupported.append("--baseline")
    if include_tool_outputs:
        unsupported.append("--include-tool-outputs")
    if no_artifacts:
        unsupported.append("--no-artifacts")
    if judge_provider:
        unsupported.append("--judge-provider")
    if judge_model:
        unsupported.append("--judge-model")
    if judge_api_key:
        unsupported.append("--judge-api-key")
    if no_judges:
        unsupported.append("--no-judges")

    if unsupported:
        raise click.ClickException(
            "Cloud eval does not support these local-only options yet: "
            + ", ".join(unsupported)
        )


async def _wait_for_cloud_eval_report(
    *,
    client: DaitaAPIClient,
    submitted: dict,
    timeout: int,
    quiet: bool,
) -> dict:
    last_status = "queued"

    async def _on_poll(execution: dict, _elapsed: float) -> None:
        nonlocal last_status
        status = execution.get("status") or ""
        if status != last_status and not quiet:
            click.echo(f"  Cloud eval {status}")
            last_status = status

    try:
        return await wait_for_eval_report(
            client,
            submitted,
            timeout_seconds=timeout,
            on_poll=_on_poll,
        )
    except LookupError:
        raise click.ClickException("Cloud eval completed but no eval run was found.")
    except TimeoutError:
        raise click.ClickException(
            f"Cloud eval timed out after {timeout}s. "
            f"Execution ID: {submitted['execution_id']}"
        )


def _coerce_report(report: dict):
    try:
        from daita.evals import EvalReport

        return EvalReport.model_validate(report)
    except Exception:
        return report


def _filter_cases(config, config_path: Path, selected_cases: set[str]) -> None:
    from daita.evals.datasets import expand_cases

    expanded = expand_cases(config, config_path=str(config_path))
    filtered = [case for case in expanded if case.id in selected_cases]
    found = {case.id for case in filtered}
    missing = sorted(selected_cases - found)
    if missing:
        raise click.ClickException(f"Eval case not found: {', '.join(missing)}")
    config.cases = filtered
    config.dataset = None


def _latest_failed_cases(project_root: Path, config) -> set[str]:
    output_root = project_root / config.artifacts.output_dir
    if not output_root.exists():
        return set()

    report_paths = sorted(
        output_root.glob("*/report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in report_paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        suite = data.get("suite") or {}
        if suite.get("name") != config.name:
            continue
        cases = data.get("cases") or []
        return {
            str(case.get("case_id"))
            for case in cases
            if case.get("status") == "failed" and case.get("case_id")
        }
    return set()


def _override_runs(config, runs: int) -> None:
    config.defaults.runs = runs
    config.case_template.runs = runs
    for case in config.cases:
        case.runs = runs


def _include_tool_outputs(config) -> None:
    config.artifacts.include_tool_outputs = True
    template_judge = config.case_template.expectations.judge
    if template_judge:
        template_judge.include_tool_outputs = True
    for case in config.cases:
        if case.expectations.judge:
            case.expectations.judge.include_tool_outputs = True


def _disable_judges(config) -> None:
    config.case_template.expectations.judge = None
    for case in config.cases:
        case.expectations.judge = None


def _override_judges(
    config,
    *,
    provider: str | None,
    model: str | None,
    api_key: str | None,
) -> None:
    template_judge = config.case_template.expectations.judge
    if template_judge:
        if provider:
            template_judge.provider = provider
        if model:
            template_judge.model = model
        if api_key:
            template_judge.api_key = api_key
    for case in config.cases:
        judge = case.expectations.judge
        if not judge:
            continue
        if provider:
            judge.provider = provider
        if model:
            judge.model = model
        if api_key:
            judge.api_key = api_key


def _resolve_optional_path(project_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = project_root / path
    return path


def _add_project_to_path(project_root: Path) -> None:
    root = str(project_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _render_report(report, output_format: str, *, quiet: bool, verbose: bool) -> str:
    if quiet:
        artifact_path = _report_artifact_path(report)
        path = f"  Output: {artifact_path}" if artifact_path else ""
        return f"{_report_status(report).upper()}{path}"

    if output_format == "json":
        if hasattr(report, "model_dump_json"):
            return report.model_dump_json(indent=2)
        return json.dumps(report, indent=2, sort_keys=True, default=str)

    try:
        from daita.evals.reporters import render_junit, render_markdown, render_pretty
    except Exception:
        if output_format == "markdown":
            return _render_markdown_dict(_report_dict(report)).rstrip()
        if output_format == "junit":
            return _render_junit_dict(_report_dict(report)).rstrip()
        return _render_pretty_dict(_report_dict(report))

    if output_format == "markdown":
        return render_markdown(report).rstrip()
    if output_format == "junit":
        return render_junit(report).rstrip()

    pretty = render_pretty(report)
    baseline = _render_baseline_comparison(report)
    if baseline:
        pretty = f"{pretty}\n\n{baseline}"
    if verbose:
        details = _render_verbose_details(report)
        if details:
            pretty = f"{pretty}\n\n{details}"
    return pretty


def _report_status(report) -> str:
    if isinstance(report, dict):
        return str(report.get("status") or "failed")
    return str(getattr(report, "status", "failed"))


def _report_artifact_path(report) -> str:
    if isinstance(report, dict):
        return str(
            report.get("artifact_path") or report.get("artifact_s3_prefix") or ""
        )
    return str(getattr(report, "artifact_path", "") or "")


def _report_dict(report) -> dict:
    if isinstance(report, dict):
        return report
    if hasattr(report, "model_dump"):
        return report.model_dump(mode="json")
    return {}


def _render_pretty_dict(report: dict) -> str:
    suite = report.get("suite") or {}
    agent = report.get("agent") or {}
    summary = report.get("summary") or {}
    lines = [
        f"Daita Eval: {suite.get('name', 'eval-suite')}",
        f"Run: {report.get('run_id', 'unknown')}  Agent: {agent.get('agent_name') or 'unknown'}  Model: {agent.get('model') or 'unknown'}",
        "",
        "Summary",
        f"  Cases:  {summary.get('cases_passed', 0)} passed / {summary.get('cases_failed', 0)} failed / {summary.get('cases_warned', 0)} warned",
        f"  Runs:   {summary.get('runs_passed', 0)} passed / {summary.get('runs_failed', 0)} failed",
        f"  Score:  {float(report.get('score') or 0) * 100:.1f}%",
        f"  Cost:   ${float(summary.get('total_cost') or 0):.4f}",
        f"  Time:   {float(summary.get('total_latency_ms') or 0) / 1000:.1f}s",
    ]
    artifact_path = _report_artifact_path(report)
    if artifact_path:
        lines.append(f"  Output: {artifact_path}")
    failures = report.get("failures") or []
    if failures:
        lines.extend(["", "Failures"])
        for failure in failures:
            lines.append(
                f"  FAIL {failure.get('case_id', 'unknown')} "
                f"{failure.get('run_id') or ''}".rstrip()
            )
            lines.append(
                f"    - {failure.get('code', 'failure')}: "
                f"{failure.get('message', '')}"
            )
    return "\n".join(lines)


def _render_markdown_dict(report: dict) -> str:
    summary = report.get("summary") or {}
    suite = report.get("suite") or {}
    return "\n".join(
        [
            f"# Daita Eval: {suite.get('name', 'eval-suite')}",
            "",
            f"- Run: `{report.get('run_id', 'unknown')}`",
            f"- Status: `{report.get('status', 'unknown')}`",
            f"- Score: `{float(report.get('score') or 0) * 100:.1f}%`",
            f"- Cases: `{summary.get('cases_passed', 0)}` passed / `{summary.get('cases_failed', 0)}` failed / `{summary.get('cases_warned', 0)}` warned",
            f"- Runs: `{summary.get('runs_passed', 0)}` passed / `{summary.get('runs_failed', 0)}` failed",
            "",
        ]
    )


def _render_junit_dict(report: dict) -> str:
    from xml.sax.saxutils import escape

    suite = report.get("suite") or {}
    summary = report.get("summary") or {}
    cases = report.get("cases") or []
    lines = [
        f'<testsuite name="{escape(str(suite.get("name", "eval-suite")))}" '
        f'tests="{int(summary.get("cases_total") or len(cases))}" '
        f'failures="{int(summary.get("cases_failed") or 0)}">'
    ]
    failures = report.get("failures") or []
    for case in cases:
        case_id = str(case.get("case_id") or "case")
        lines.append(f'  <testcase classname="daita.eval" name="{escape(case_id)}">')
        if case.get("status") == "failed":
            messages = [
                str(item.get("message") or "")
                for item in failures
                if item.get("case_id") == case_id
            ]
            message = escape("; ".join(messages) or "case failed")
            lines.append(f'    <failure message="{message}">{message}</failure>')
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def _render_baseline_comparison(report) -> str:
    comparison = getattr(report, "baseline_comparison", None)
    if not comparison:
        return ""

    lines = [
        "Baseline",
        f"  Status: {comparison.get('status', 'unknown')}",
        f"  Score delta: {comparison.get('score_delta', 0) * 100:.1f} points",
        f"  Cost delta: ${comparison.get('cost_delta', 0):.4f}",
        f"  Latency delta: {comparison.get('latency_ms_delta', 0) / 1000:.1f}s",
    ]
    regressions = comparison.get("regressions") or []
    if regressions:
        lines.append("  Regressions:")
        for item in regressions:
            lines.append(f"    - {item.get('code')}: {item.get('observed')}")
    return "\n".join(lines)


def _render_verbose_details(report) -> str:
    lines = ["Details"]
    for case in report.cases:
        for run in case.runs:
            preview = run.final_answer_preview
            if preview:
                lines.append(f"  {case.case_id}/{run.run_id}: {preview}")
            if run.tool_calls:
                tools = " -> ".join(call.name for call in run.tool_calls)
                lines.append(f"    tools: {tools}")
    return "\n".join(lines) if len(lines) > 1 else ""
