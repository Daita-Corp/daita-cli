import json

import pytest

pytest.importorskip("mcp")

import daita_cli.mcp_server as mcp
from daita_cli.mcp_server import call_tool, list_tools


class FakeDaitaAPIClient:
    calls = []
    responses = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, path, params=None):
        self.calls.append(("GET", path, params))
        return self.responses[path]

    async def post(self, path, json=None):
        self.calls.append(("POST", path, json))
        return self.responses[path]


@pytest.mark.asyncio
async def test_database_agent_mcp_tools_are_registered():
    tools = await list_tools()
    names = {tool.name for tool in tools}

    assert "list_database_agents" in names
    assert "get_database_agent" in names
    assert "refresh_database_agent_catalog" in names
    assert not any("webhook" in name for name in names)


@pytest.mark.asyncio
async def test_database_agent_mcp_tools_use_hosted_paths(monkeypatch):
    FakeDaitaAPIClient.calls = []
    FakeDaitaAPIClient.responses = {
        "/api/v1/agents/agents/database": {
            "database_agents": [
                {
                    "agent_id": "db_1",
                    "name": "revenue",
                    "status": "active",
                    "source": {"name": "warehouse"},
                    "catalog": {"status": "fresh"},
                    "large_payload": {"keep": "out of mcp summary"},
                }
            ]
        },
        "/api/v1/agents/agents/db_1/database": {"id": "db_1", "name": "revenue"},
        "/api/v1/agents/agents/db_1/database/refresh": {
            "status": "refreshing",
            "agent_id": "db_1",
        },
    }
    monkeypatch.setattr(mcp, "DaitaAPIClient", FakeDaitaAPIClient)

    listed = json.loads((await call_tool("list_database_agents", {}))[0].text)
    detail = json.loads(
        (await call_tool("get_database_agent", {"agent_id": "db_1"}))[0].text
    )
    refresh = json.loads(
        (
            await call_tool("refresh_database_agent_catalog", {"agent_id": "db_1"})
        )[0].text
    )

    assert FakeDaitaAPIClient.calls == [
        ("GET", "/api/v1/agents/agents/database", None),
        ("GET", "/api/v1/agents/agents/db_1/database", None),
        ("POST", "/api/v1/agents/agents/db_1/database/refresh", None),
    ]
    assert listed["database_agents"] == [
        {
            "id": "db_1",
            "name": "revenue",
            "status": "active",
            "source": "warehouse",
            "catalog_freshness": "fresh",
        }
    ]
    assert detail == {"id": "db_1", "name": "revenue"}
    assert refresh == {"status": "refreshing", "agent_id": "db_1"}
