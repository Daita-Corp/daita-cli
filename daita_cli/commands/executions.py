import click
from daita_cli.command_helpers import api_command


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
    """List executions."""
    params = {"limit": limit}
    if status:
        params["status"] = status
    if target_type:
        params["target_type"] = target_type
    data = await client.get("/api/v1/autonomous/executions", params=params)
    items = data if isinstance(data, list) else data.get("executions", data.get("items", []))
    formatter.list_items(
        items,
        columns=["execution_id", "target_name", "target_type", "status", "created_at", "duration_ms"],
        title="Executions",
    )


@executions.command("show")
@click.argument("execution_id")
@api_command
async def show_execution(client, formatter, execution_id):
    """Show execution details."""
    data = await client.get(f"/api/v1/autonomous/executions/{execution_id}")
    formatter.item(data)


@executions.command("logs")
@click.argument("execution_id")
@click.option("--follow", "-f", is_flag=True, help="Poll until complete")
@api_command
async def execution_logs(client, formatter, execution_id, follow):
    """Show logs for an execution."""
    import asyncio
    import sys

    if follow:
        while True:
            data = await client.get(f"/api/v1/autonomous/executions/{execution_id}")
            formatter.item(data, fields=["execution_id", "status", "created_at", "duration_ms", "error"])
            if data.get("status") in ("completed", "success", "failed", "error", "cancelled"):
                break
            if not formatter.is_json:
                print("  polling...")
            await asyncio.sleep(2)
    else:
        data = await client.get(f"/api/v1/autonomous/executions/{execution_id}")
        formatter.item(data)


@executions.command("cancel")
@click.argument("execution_id")
@api_command
async def cancel_execution(client, formatter, execution_id):
    """Cancel a running execution."""
    data = await client.delete(f"/api/v1/autonomous/executions/{execution_id}")
    formatter.success(data, message=f"Execution {execution_id} cancelled.")
