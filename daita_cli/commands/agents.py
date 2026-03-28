import click
from daita_cli.command_helpers import api_command


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
    formatter.list_items(
        items,
        columns=["id", "name", "type", "status", "created_at"],
        title="Agents",
    )


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
    formatter.list_items(
        items,
        columns=["id", "name", "type", "status", "deployed_at"],
        title="Deployed Agents",
    )
