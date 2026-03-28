"""
Conversations — requires user_id for all requests.
The backend scopes conversations per user. From the CLI, user_id defaults to "cli"
(all CLI-created conversations share this scope). Override with --user-id.
"""

import click
from daita_cli.command_helpers import api_command

_USER_ID_OPT = click.option(
    "--user-id", default="cli", show_default=True,
    help="User ID for scoping conversations (default: 'cli')",
)


@click.group()
def conversations():
    """Manage conversations."""
    pass


@conversations.command("list")
@_USER_ID_OPT
@click.option("--agent-name")
@click.option("--limit", default=20, show_default=True)
@api_command
async def list_conversations(client, formatter, user_id, agent_name, limit):
    """List conversations."""
    params = {"user_id": user_id, "limit": limit}
    if agent_name:
        params["agent_name"] = agent_name
    data = await client.get("/api/v1/conversations", params=params)
    items = data if isinstance(data, list) else data.get("conversations", data.get("items", []))
    formatter.list_items(
        items,
        columns=["id", "title", "agent_name", "created_at"],
        title="Conversations",
    )


@conversations.command("show")
@click.argument("conversation_id")
@_USER_ID_OPT
@api_command
async def show_conversation(client, formatter, conversation_id, user_id):
    """Show conversation details."""
    data = await client.get(f"/api/v1/conversations/{conversation_id}", params={"user_id": user_id})
    formatter.item(data)


@conversations.command("create")
@click.option("--agent-name", required=True)
@click.option("--title")
@_USER_ID_OPT
@api_command
async def create_conversation(client, formatter, agent_name, title, user_id):
    """Create a new conversation."""
    payload = {"agent_name": agent_name, "user_id": user_id}
    if title:
        payload["title"] = title
    data = await client.post("/api/v1/conversations", json=payload)
    formatter.success(data, message=f"Conversation created: {data.get('id', '')}")


@conversations.command("delete")
@click.argument("conversation_id")
@_USER_ID_OPT
@api_command
async def delete_conversation(client, formatter, conversation_id, user_id):
    """Delete a conversation."""
    data = await client.delete(
        f"/api/v1/conversations/{conversation_id}",
        params={"user_id": user_id},
    )
    formatter.success(data, message=f"Conversation {conversation_id} deleted.")
