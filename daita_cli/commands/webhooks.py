import click
from daita_cli.command_helpers import api_command


@click.group()
def webhooks():
    """View webhooks."""
    pass


@webhooks.command("list")
@api_command
async def list_webhooks(client, formatter):
    """List webhook URLs for your organization."""
    data = await client.get("/api/v1/webhooks/webhooks/list")
    items = data if isinstance(data, list) else data.get("webhooks", data.get("items", []))
    formatter.list_items(
        items,
        columns=["id", "name", "url", "agent_name", "created_at"],
        title="Webhooks",
    )
