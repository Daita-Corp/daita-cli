import click
from daita_cli.command_helpers import api_command, normalize_rows


_AGENT_ROW_SCHEMA = {
    "id": ("id", "agent_id", "agentId"),
    "name": ("name", "display_name", "displayName"),
    "type": ("type", "agent_type", "agentType"),
    "status": ("status",),
    "created_at": ("created_at", "createdAt", "startTime"),
}

_DEPLOYED_AGENT_ROW_SCHEMA = {
    "id": ("id", "agent_id", "agentId"),
    "name": ("name", "display_name", "displayName"),
    "type": ("type", "agent_type", "agentType"),
    "status": ("status",),
    "deployed_at": ("deployed_at", "deployedAt", "created_at", "createdAt"),
    "version": ("version", "deployment_version"),
}


@click.group()
def agents():
    """Manage agents."""
    pass


@agents.command("list")
@click.option("--type", "agent_type", type=click.Choice(["agent", "workflow"]), help="Filter by type")
@click.option("--status", type=click.Choice(["active", "inactive"]), help="Filter by status")
@click.option("--page", default=1, show_default=True, help="Page number")
@click.option("--per-page", default=20, show_default=True, help="Items per page")
@api_command
async def list_agents(client, formatter, agent_type, status, page, per_page):
    """List agents."""
    params = {"page": page, "per_page": per_page}
    if agent_type:
        params["agent_type"] = agent_type
    if status:
        params["status_filter"] = status
    data = await client.get("/api/v1/agents/agents", params=params)
    items = data if isinstance(data, list) else data.get("agents", data.get("items", []))
    rows = normalize_rows(items, _AGENT_ROW_SCHEMA)
    formatter.list_items(rows, columns=list(_AGENT_ROW_SCHEMA.keys()), title="Agents")


@agents.command("show")
@click.argument("agent_id")
@api_command
async def show_agent(client, formatter, agent_id):
    """Show agent details."""
    data = await client.get(f"/api/v1/agents/agents/{agent_id}")
    formatter.item(data)


@agents.command("deployed")
@api_command
async def deployed_agents(client, formatter):
    """List deployed agents with configuration."""
    data = await client.get("/api/v1/agents/agents/deployed")
    items = data if isinstance(data, list) else data.get("agents", data.get("items", []))
    rows = normalize_rows(items, _DEPLOYED_AGENT_ROW_SCHEMA)
    formatter.list_items(rows, columns=list(_DEPLOYED_AGENT_ROW_SCHEMA.keys()), title="Deployed Agents")
