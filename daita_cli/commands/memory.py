import click
from daita_cli.command_helpers import api_command


@click.group()
def memory():
    """View agent memory."""
    pass


@memory.command("status")
@click.option("--project", required=True, help="Project name")
@api_command
async def memory_status(client, formatter, project):
    """Show memory status."""
    data = await client.get("/api/v1/memory/status", params={"project": project})
    formatter.item(data)


@memory.command("show")
@click.argument("workspace")
@click.option("--full", is_flag=True, help="Download complete files")
@click.option("--limit", default=50, show_default=True)
@click.option("--project", required=True, help="Project name")
@api_command
async def show_memory(client, formatter, workspace, full, limit, project):
    """Show memory contents for a workspace."""
    params = {"limit": limit, "project": project}
    if full:
        params["full"] = "true"
    data = await client.get(f"/api/v1/memory/workspaces/{workspace}", params=params)
    if formatter.is_json:
        import json, sys

        print(json.dumps(data, default=str))
    else:
        items = (
            data
            if isinstance(data, list)
            else data.get(
                "items", data.get("memories", [data] if isinstance(data, dict) else [])
            )
        )
        formatter.list_items(
            items,
            columns=["id", "key", "value", "created_at"],
            title=f"Memory: {workspace}",
        )
