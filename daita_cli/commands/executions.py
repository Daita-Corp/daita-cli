import click
from daita_cli.command_helpers import api_command, normalize_rows, pick


_EXECUTION_ROW_SCHEMA = {
    "execution_id": ("id", "execution_id", "executionId"),
    "target": ("name", "target_name", "targetName", "agent_name", "agentName", "workflow_name"),
    "type": ("type", "target_type", "targetType", "operationType"),
    "status": ("status",),
    "created_at": ("startTime", "created_at", "createdAt", "start_time"),
    "duration_ms": ("duration", "duration_ms", "latency_ms"),
}

# Candidate keys for client-side sort (newest first). First present wins.
_EXECUTION_SORT_KEYS = ("startTime", "created_at", "createdAt", "start_time")


def _sort_newest_first(items: list[dict]) -> list[dict]:
    """Sort by the first available timestamp key, descending. Missing values
    fall to the bottom so recent runs always surface first."""
    return sorted(
        items,
        key=lambda it: (pick(it, *_EXECUTION_SORT_KEYS, default="") or ""),
        reverse=True,
    )


@click.group(invoke_without_command=True)
@click.option("--limit", default=10, show_default=True)
@click.option("--status", type=click.Choice(["queued", "running", "completed", "failed", "cancelled"]))
@click.option("--type", "target_type", type=click.Choice(["agent", "workflow"]))
@click.pass_context
def executions(ctx, limit, status, target_type):
    """Manage executions."""
    if ctx.invoked_subcommand is None:
        # Backward compat: `daita executions` with no subcommand → list
        ctx.invoke(list_executions, limit=limit, status=status, target_type=target_type)


@executions.command("list")
@click.option("--limit", default=10, show_default=True)
@click.option("--status", type=click.Choice(["queued", "running", "completed", "failed", "cancelled"]))
@click.option("--type", "target_type", type=click.Choice(["agent", "workflow"]))
@api_command
async def list_executions(client, formatter, limit, status, target_type):
    """List executions (all sources, newest first)."""
    # Backend query param is `status_filter`, not `status`.
    params = {"limit": limit, "offset": 0}
    if status:
        params["status_filter"] = status
    if target_type:
        params["target_type"] = target_type
    data = await client.get("/api/v1/executions/", params=params)
    items = data if isinstance(data, list) else data.get("executions", data.get("items", []))
    items = _sort_newest_first(items)[:limit]
    rows = normalize_rows(items, _EXECUTION_ROW_SCHEMA)
    formatter.list_items(
        rows,
        columns=list(_EXECUTION_ROW_SCHEMA.keys()),
        title="Executions",
    )


@executions.command("show")
@click.argument("execution_id")
@api_command
async def show_execution(client, formatter, execution_id):
    """Show execution details."""
    data = await client.get(f"/api/v1/executions/{execution_id}")
    formatter.item(data)


@executions.command("logs")
@click.argument("execution_id")
@click.option("--follow", "-f", is_flag=True, help="Poll until complete")
@api_command
async def execution_logs(client, formatter, execution_id, follow):
    """Show logs for an execution."""
    import asyncio

    if follow:
        while True:
            data = await client.get(f"/api/v1/executions/{execution_id}")
            formatter.item(data, fields=["execution_id", "status", "created_at", "duration_ms", "error"])
            if data.get("status") in ("completed", "success", "failed", "error", "cancelled"):
                break
            if not formatter.is_json:
                print("  polling...")
            await asyncio.sleep(2)
    else:
        data = await client.get(f"/api/v1/executions/{execution_id}")
        formatter.item(data)


@executions.command("cancel")
@click.argument("execution_id")
@api_command
async def cancel_execution(client, formatter, execution_id):
    """Cancel a running execution."""
    data = await client.delete(f"/api/v1/executions/{execution_id}")
    formatter.success(data, message=f"Execution {execution_id} cancelled.")
