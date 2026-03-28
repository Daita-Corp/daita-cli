"""
daita run — execute an agent or workflow remotely.

Polls until completion; suppresses spinner in JSON mode.
"""

import asyncio
import json
import sys
import time

import click

from daita_cli.api_client import DaitaAPIClient, APIError, AuthError
from daita_cli.output import OutputFormatter
from daita_cli import __version__

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _ansi() -> bool:
    return sys.stdout.isatty()


def _fmt_elapsed(s: float) -> str:
    s = int(s)
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


@click.command("run")
@click.argument("target")
@click.option("--type", "target_type", default="agent", type=click.Choice(["agent", "workflow"]))
@click.option("--data", "data_file", help="JSON file with input data")
@click.option("--data-json", help="JSON string with input data")
@click.option("--task", default="process", show_default=True)
@click.option("--follow", "-f", is_flag=True, help="Follow progress in real-time")
@click.option("--timeout", default=300, show_default=True, type=int, help="Timeout seconds")
@click.pass_context
def run_command(ctx, target, target_type, data_file, data_json, task, follow, timeout):
    """Execute an agent or workflow remotely."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())

    async def _run():
        # Load input data
        input_data = {}
        if data_file:
            try:
                with open(data_file) as f:
                    input_data = json.load(f)
            except Exception as e:
                raise click.ClickException(f"Failed to load data file: {e}")
        elif data_json:
            try:
                input_data = json.loads(data_json)
            except Exception as e:
                raise click.ClickException(f"Invalid JSON: {e}")

        request = {
            "data": input_data,
            "timeout_seconds": timeout,
            "execution_source": "cli",
            "source_metadata": {"cli_version": __version__, "command": f"daita run {target}"},
        }
        if target_type == "agent":
            request["agent_name"] = target
            request["task"] = task
        else:
            request["workflow_name"] = target

        async with DaitaAPIClient() as client:
            formatter.progress(f"  Submitting {target_type} '{target}'...")
            result = await client.post("/api/v1/executions/execute", json=request)
            execution_id = result["execution_id"]

            if formatter.is_json:
                # JSON mode: poll silently
                await _poll(client, formatter, execution_id, target, timeout)
            else:
                await _poll_with_spinner(client, formatter, execution_id, target, timeout)

    try:
        asyncio.run(_run())
    except AuthError as e:
        formatter.error("AUTH_ERROR", str(e))
        sys.exit(2)
    except APIError as e:
        formatter.error("API_ERROR", str(e), {"status_code": e.status_code})
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\n  Detached — execution continues in background.", err=True)
        sys.exit(130)
    except click.ClickException:
        raise
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


async def _poll(client, formatter, execution_id, agent_name, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1)
        data = await client.get(f"/api/v1/executions/{execution_id}")
        status = data.get("status", "")
        if status in ("completed", "success"):
            formatter.success(data)
            return
        if status in ("failed", "error"):
            formatter.error("EXECUTION_FAILED", data.get("error", "Execution failed"), data)
            sys.exit(1)
        if status == "cancelled":
            formatter.error("EXECUTION_CANCELLED", "Execution was cancelled")
            sys.exit(1)
    formatter.error("TIMEOUT", f"Execution timed out after {timeout}s. ID: {execution_id}")
    sys.exit(1)


async def _poll_with_spinner(client, formatter, execution_id, agent_name, timeout):
    use_ansi = _ansi()
    start = time.time()
    deadline = start + timeout
    frame_idx = 0
    status = "queued"

    async def _spinner():
        nonlocal frame_idx
        while True:
            if use_ansi:
                frame = _SPINNER[frame_idx % len(_SPINNER)]
                elapsed = _fmt_elapsed(time.time() - start)
                sys.stdout.write(f"\r\033[K  {frame}  {agent_name}  {status}  {elapsed}")
                sys.stdout.flush()
                frame_idx += 1
            await asyncio.sleep(0.08)

    spin_task = asyncio.create_task(_spinner()) if use_ansi else None

    try:
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            data = await client.get(f"/api/v1/executions/{execution_id}")
            status = data.get("status", "")

            if status in ("completed", "success"):
                elapsed = _fmt_elapsed(time.time() - start)
                if use_ansi:
                    sys.stdout.write(f"\r\033[K  ✓  {agent_name}  completed  {elapsed}\n")
                    sys.stdout.flush()
                _print_result(data)
                return

            if status in ("failed", "error"):
                elapsed = _fmt_elapsed(time.time() - start)
                if use_ansi:
                    sys.stdout.write(f"\r\033[K  ✗  {agent_name}  failed  {elapsed}\n")
                    sys.stdout.flush()
                if data.get("error"):
                    click.echo(f"\n  Error: {data['error']}")
                sys.exit(1)

            if status == "cancelled":
                if use_ansi:
                    sys.stdout.write(f"\r\033[K  ✗  {agent_name}  cancelled\n")
                    sys.stdout.flush()
                sys.exit(1)
    finally:
        if spin_task:
            spin_task.cancel()
            await asyncio.gather(spin_task, return_exceptions=True)

    click.echo(f"\n  Execution still running after {timeout}s. ID: {execution_id}")
    sys.exit(1)


def _print_result(data: dict) -> None:
    result = data.get("result")
    if not result:
        return
    click.echo("")
    if isinstance(result, str):
        preview = result[:400] + ("…" if len(result) > 400 else "")
        click.echo(f"  {preview}")
    elif isinstance(result, dict):
        if "message" in result:
            click.echo(f"  {str(result['message'])[:200]}")
        else:
            for k, v in list(result.items())[:6]:
                click.echo(f"  {k}: {str(v)[:80]}")
    click.echo("")
