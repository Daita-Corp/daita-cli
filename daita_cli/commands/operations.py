"""
daita operations — view platform operations.

Note: list and stats endpoints require JWT (dashboard) auth, not API key auth.
These commands will return 401 when called with DAITA_API_KEY only.
They are included for completeness; use the Daita dashboard for operations analytics.
"""

import click
from daita_cli.command_helpers import api_command


@click.group()
def operations():
    """View platform operations (requires dashboard auth)."""
    pass


@operations.command("list")
@click.option("--limit", default=20, show_default=True)
@click.option("--status", "status_filter", type=click.Choice(["success", "error", "timeout"]))
@click.option("--agent-id", help="Filter by agent ID")
@api_command
async def list_operations(client, formatter, limit, status_filter, agent_id):
    """List operations. Requires dashboard (JWT) auth — not available with API key only."""
    params = {"per_page": limit}
    if status_filter:
        params["status_filter"] = status_filter
    if agent_id:
        params["agent_id"] = agent_id
    data = await client.get("/api/v1/operations", params=params)
    items = data if isinstance(data, list) else data.get("operations", data.get("items", []))
    formatter.list_items(
        items,
        columns=["operation_id", "agent_name", "status", "timestamp", "latency_ms"],
        title="Operations",
    )


@operations.command("stats")
@click.option("--period", type=click.Choice(["24h", "7d", "30d"]), default="24h", show_default=True)
@api_command
async def operation_stats(client, formatter, period):
    """Show operation statistics. Requires dashboard (JWT) auth — not available with API key only."""
    data = await client.get("/api/v1/operations/stats", params={"period": period})
    formatter.item(data)
