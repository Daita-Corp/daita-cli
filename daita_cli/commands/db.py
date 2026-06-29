"""Database-agent command group."""

from __future__ import annotations

import asyncio
import functools
import sys
from typing import Any

import click
import httpx

from daita_cli.command_helpers import api_command
from daita_cli.commands.dev import dev_command
from daita_cli.db_agents import (
    database_agent_columns,
    database_agent_rows,
    get_database_agent,
    list_database_agents,
    refresh_database_agent_catalog,
)
from daita_cli import local_server_client
from daita_cli.local_server_client import DEFAULT_LOCAL_SERVER_URL


def _local_db_command(f):
    @functools.wraps(f)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        from daita_cli.output import OutputFormatter

        formatter = (ctx.obj or {}).get("formatter", OutputFormatter())

        try:
            asyncio.run(f(formatter, *args, **kwargs))
        except click.ClickException as exc:
            formatter.error("USAGE_ERROR", exc.message)
            sys.exit(exc.exit_code)
        except httpx.HTTPStatusError as exc:
            response = exc.response
            message = f"Local Agent Server returned HTTP {response.status_code}"
            if response.text:
                message = f"{message}: {response.text}"
            formatter.error("LOCAL_SERVER_ERROR", message)
            sys.exit(1)
        except httpx.RequestError as exc:
            formatter.error(
                "LOCAL_SERVER_UNAVAILABLE",
                f"Could not connect to the local Agent Server: {exc}",
            )
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(130)
        except Exception as exc:
            formatter.error("ERROR", str(exc))
            sys.exit(1)

    return wrapper


def _require_local(command: str, use_local: bool) -> None:
    if not use_local:
        raise click.ClickException(
            f"`daita db {command}` currently supports only --local. "
            "Start a local Agent Server with `daita db dev` and rerun with --local."
        )


def _runtime_summary(runtime: Any) -> dict[str, Any] | None:
    if not isinstance(runtime, dict):
        return None

    summary: dict[str, Any] = {}
    for key, output_key in (
        ("tasks", "task_count"),
        ("evidence", "evidence_count"),
        ("events", "event_count"),
    ):
        value = runtime.get(key)
        if isinstance(value, list):
            summary[output_key] = len(value)

    for key in ("telemetry", "diagnostics"):
        value = runtime.get(key)
        if value not in (None, {}, []):
            summary[key] = value

    return summary or None


def _run_output(data: Any) -> Any:
    if not isinstance(data, dict):
        return data

    output: dict[str, Any] = {}
    for key in ("answer", "operation_id", "status", "warnings"):
        if key in data:
            output[key] = data[key]

    for key, value in data.items():
        if key not in output:
            output[key] = value

    runtime = data.get("runtime") or data.get("_daita_runtime") or data.get(
        "runtime_result"
    )
    summary = _runtime_summary(runtime)
    if summary and "runtime_summary" not in output:
        output["runtime_summary"] = summary
    return output


@click.group("db")
def db_group():
    """Database-agent workflows."""


@db_group.command("list")
@api_command
async def list_db_agents(client, formatter):
    """List hosted database agents."""
    data = await list_database_agents(client)
    rows = database_agent_rows(data)
    formatter.list_items(rows, columns=database_agent_columns(), title="Database Agents")


@db_group.command("show")
@click.argument("agent_id")
@api_command
async def show_db_agent(client, formatter, agent_id):
    """Show hosted database-agent details."""
    data = await get_database_agent(client, agent_id)
    formatter.item(data)


@db_group.command("refresh")
@click.argument("agent_id")
@api_command
async def refresh_db_agent(client, formatter, agent_id):
    """Refresh a hosted database-agent catalog."""
    data = await refresh_database_agent_catalog(client, agent_id)
    formatter.success(data)


@db_group.command("ask")
@click.argument("agent_name")
@click.argument("prompt")
@click.option("--local", "use_local", is_flag=True, help="Use the local Agent Server.")
@click.option(
    "--server-url",
    default=DEFAULT_LOCAL_SERVER_URL,
    show_default=True,
    help="Local Agent Server URL.",
)
@click.option("--session-id", help="Optional local runtime session ID.")
@_local_db_command
async def ask_db_agent(formatter, agent_name, prompt, use_local, server_url, session_id):
    """Run a prompt through a local database agent."""
    _require_local("ask", use_local)
    data = await local_server_client.call_local_agent(
        agent_name,
        prompt,
        server_url=server_url,
        session_id=session_id,
    )
    formatter.item(_run_output(data))


@db_group.command("inspect")
@click.argument("agent_name")
@click.option("--local", "use_local", is_flag=True, help="Use the local Agent Server.")
@click.option(
    "--server-url",
    default=DEFAULT_LOCAL_SERVER_URL,
    show_default=True,
    help="Local Agent Server URL.",
)
@_local_db_command
async def inspect_db_agent(formatter, agent_name, use_local, server_url):
    """Inspect a local database agent."""
    _require_local("inspect", use_local)
    formatter.item(
        await local_server_client.get_local_server_agent(agent_name, server_url)
    )


@db_group.command("evidence")
@click.argument("operation_id")
@click.option("--local", "use_local", is_flag=True, help="Use the local Agent Server.")
@click.option(
    "--server-url",
    default=DEFAULT_LOCAL_SERVER_URL,
    show_default=True,
    help="Local Agent Server URL.",
)
@_local_db_command
async def db_operation_evidence(formatter, operation_id, use_local, server_url):
    """Fetch local runtime evidence for an operation."""
    _require_local("evidence", use_local)
    formatter.item(
        await local_server_client.get_local_server_operation_evidence(
            operation_id, server_url
        )
    )


@db_group.command("tasks")
@click.argument("operation_id")
@click.option("--local", "use_local", is_flag=True, help="Use the local Agent Server.")
@click.option(
    "--server-url",
    default=DEFAULT_LOCAL_SERVER_URL,
    show_default=True,
    help="Local Agent Server URL.",
)
@_local_db_command
async def db_operation_tasks(formatter, operation_id, use_local, server_url):
    """Fetch local runtime tasks for an operation."""
    _require_local("tasks", use_local)
    formatter.item(
        await local_server_client.get_local_server_operation_tasks(
            operation_id, server_url
        )
    )


db_group.add_command(dev_command)
