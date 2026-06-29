"""Hosted database-agent API helpers shared by CLI and MCP tools."""

from __future__ import annotations

from typing import Any

from daita_cli.api_client import DaitaAPIClient
from daita_cli.command_helpers import pick

DATABASE_AGENTS_PATH = "/api/v1/agents/agents/database"
AGENTS_PATH = "/api/v1/agents/agents"

_DATABASE_AGENT_ROW_SCHEMA = {
    "id": ("id", "agent_id", "agentId"),
    "name": ("name", "agent_name", "agentName", "display_name", "displayName"),
    "status": ("status",),
    "source": ("source", "source_name", "sourceName", "database", "database_name"),
    "catalog_freshness": (
        "catalog_freshness",
        "catalogFreshness",
        "catalog_status",
        "catalogStatus",
        "catalog_updated_at",
        "catalogUpdatedAt",
        "last_catalog_refresh",
        "lastCatalogRefresh",
    ),
}


async def list_database_agents(client: DaitaAPIClient) -> Any:
    return await client.get(DATABASE_AGENTS_PATH)


async def get_database_agent(client: DaitaAPIClient, agent_id: str) -> Any:
    return await client.get(f"{AGENTS_PATH}/{agent_id}/database")


async def refresh_database_agent_catalog(client: DaitaAPIClient, agent_id: str) -> Any:
    return await client.post(f"{AGENTS_PATH}/{agent_id}/database/refresh")


def extract_database_agent_items(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("database_agents", "databaseAgents", "agents", "items"):
        items = data.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _nested_value(item: dict, parent: str, *keys: str) -> Any:
    nested = item.get(parent)
    if isinstance(nested, dict):
        return pick(nested, *keys)
    return None


def database_agent_row(item: dict) -> dict:
    row = {
        out: pick(item, *sources) for out, sources in _DATABASE_AGENT_ROW_SCHEMA.items()
    }
    if isinstance(row["source"], dict) or not row["source"]:
        row["source"] = _nested_value(item, "source", "name", "type", "database")
    if isinstance(row["catalog_freshness"], dict) or not row["catalog_freshness"]:
        row["catalog_freshness"] = _nested_value(
            item, "catalog", "freshness", "status", "updated_at", "updatedAt"
        )
    return row


def database_agent_rows(data: Any) -> list[dict]:
    return [database_agent_row(item) for item in extract_database_agent_items(data)]


def database_agent_columns() -> list[str]:
    return list(_DATABASE_AGENT_ROW_SCHEMA.keys())


def summarize_database_agent_list(data: Any) -> Any:
    rows = database_agent_rows(data)
    if isinstance(data, list):
        return rows
    if not isinstance(data, dict):
        return data
    for key in ("database_agents", "databaseAgents", "agents", "items"):
        if isinstance(data.get(key), list):
            return {**data, key: rows}
    return data
