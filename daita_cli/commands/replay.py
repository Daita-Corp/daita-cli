"""
daita replay <execution_id> — re-run an execution with identical inputs.

Inputs are fetched from the original execution and submitted as a new run.
The original is never mutated; replay produces a new execution_id tagged
`replay_of=<original>` for history.

Pairs naturally with `daita diff` — set `--diff` to auto-compare after
completion.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from daita_cli import __version__
from daita_cli.api_client import DaitaAPIClient
from daita_cli.command_helpers import api_command
from daita_cli.commands._polling import poll_until_terminal, TERMINAL_OK


def _apply_overrides(request: dict, override_json: str | None) -> dict:
    """Shallow-merge a JSON-string override onto the request dict."""
    if not override_json:
        return request
    try:
        patch = json.loads(override_json)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid --override JSON: {e}") from e
    if not isinstance(patch, dict):
        raise click.ClickException("--override must be a JSON object")
    return {**request, **patch}


def _build_replay_request(
    original: dict, *, overrides: str | None, timeout: int
) -> dict:
    """Translate an original execution record into a new submit request."""
    # Fields we inherit from the original. Missing fields are tolerated.
    source_meta = {
        "cli_version": __version__,
        "command": "daita replay",
        "replay_of": original.get("execution_id"),
    }
    base = {
        "data": original.get("data") or original.get("input_data") or {},
        "timeout_seconds": timeout,
        "execution_source": "replay",
        "source_metadata": source_meta,
    }
    if original.get("agent_name"):
        base["agent_name"] = original["agent_name"]
        base["task"] = original.get("task", "process")
    elif original.get("workflow_name"):
        base["workflow_name"] = original["workflow_name"]
    else:
        # Attempt target_name/target_type fallback
        target_name = original.get("target_name")
        target_type = original.get("target_type", "agent")
        if not target_name:
            raise click.ClickException(
                "Could not determine agent/workflow from original execution. "
                'Pass --override \'{"agent_name": "..."}\' to fix.'
            )
        if target_type == "workflow":
            base["workflow_name"] = target_name
        else:
            base["agent_name"] = target_name
            base["task"] = original.get("task", "process")
    return _apply_overrides(base, overrides)


async def replay_execution(
    client: DaitaAPIClient,
    execution_id: str,
    *,
    overrides: str | None = None,
    deployment_id: str | None = None,
    timeout: int = 300,
    on_poll=None,
) -> dict[str, Any]:
    """Submit a replay and poll until terminal. Returns the final status dict.

    Shared between the CLI command and the MCP `replay_execution` tool.
    """
    original = await client.get(f"/api/v1/executions/{execution_id}")
    request = _build_replay_request(original, overrides=overrides, timeout=timeout)
    if deployment_id:
        request["deployment_id"] = deployment_id

    submitted = await client.post("/api/v1/executions/execute", json=request)
    new_id = submitted["execution_id"]

    final = await poll_until_terminal(
        client,
        f"/api/v1/executions/{new_id}",
        timeout=timeout,
        on_poll=on_poll,
    )
    final["replay_of"] = execution_id
    return final


@click.command("replay")
@click.argument("execution_id")
@click.option(
    "--deployment",
    "deployment_id",
    help="Replay against a specific deployment version.",
)
@click.option(
    "--override",
    help='JSON patch to merge onto the replay request (e.g. \'{"task": "validate"}\').',
)
@click.option(
    "--timeout",
    default=300,
    show_default=True,
    type=int,
    help="Seconds to wait for completion.",
)
@click.option(
    "--diff",
    "auto_diff",
    is_flag=True,
    help="Run `daita diff` against the original when complete.",
)
@click.option(
    "--follow", "-f", is_flag=True, help="Print status updates during polling."
)
@api_command
async def replay_command(
    client: DaitaAPIClient,
    formatter,
    execution_id: str,
    deployment_id: str | None,
    override: str | None,
    timeout: int,
    auto_diff: bool,
    follow: bool,
):
    """Re-run an execution with identical inputs."""
    from daita_cli.commands._spinner import spinner

    async def _status_hook(data: dict, elapsed: float):
        if follow and not formatter.is_json:
            status = data.get("status", "?")
            click.echo(f"  [{elapsed:5.1f}s] {status}", err=True)

    # Spinner while we submit + poll. Suppress it when --follow is on (the
    # hook already prints per-tick status, and two animations in one line
    # would fight).
    use_spinner = not follow

    async def _run():
        return await replay_execution(
            client,
            execution_id,
            overrides=override,
            deployment_id=deployment_id,
            timeout=timeout,
            on_poll=_status_hook,
        )

    if use_spinner:
        async with spinner(f"Replaying {execution_id}…", formatter=formatter):
            final = await _run()
    else:
        formatter.progress(f"  Replaying {execution_id}...")
        final = await _run()

    if final.get("status") in TERMINAL_OK:
        formatter.success(
            final, message=f"  ✓ replay completed → {final.get('execution_id')}"
        )
    else:
        formatter.error(
            "REPLAY_FAILED",
            final.get("error") or f"replay ended with status {final.get('status')}",
            {"execution_id": final.get("execution_id"), "status": final.get("status")},
        )
        sys.exit(1)

    if auto_diff:
        new_id = final.get("execution_id")
        if not new_id:
            return
        # Re-enter via the installed command so flag handling stays consistent.
        from daita_cli.commands.diff import compute_diff

        summary = await compute_diff(client, execution_id, new_id)
        click.echo("")
        _print_diff(formatter, summary)


def _print_diff(formatter, summary: dict) -> None:
    """Tiny delegate so `--diff` doesn't need to shell out to another command."""
    from daita_cli.commands.diff import render_diff_text

    if formatter.is_json:
        print(json.dumps(summary, default=str))
    else:
        click.echo(render_diff_text(summary))
