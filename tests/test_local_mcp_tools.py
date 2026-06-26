import json

import pytest

pytest.importorskip("mcp")

from daita_cli.mcp_server import call_tool, list_tools
from daita_cli import local_server_client


@pytest.mark.asyncio
async def test_local_agent_server_mcp_tools_register_without_api_key():
    tools = await list_tools()
    names = {tool.name for tool in tools}

    assert "get_local_agent_server_status" in names
    assert "list_local_server_agents" in names
    assert "call_local_agent" in names
    assert "get_local_server_runtime_operation" in names
    assert "get_local_server_operation_evidence" in names
    assert "get_local_server_operation_tasks" in names


@pytest.mark.asyncio
async def test_local_agent_server_mcp_tools_return_structured_json(monkeypatch):
    async def status(server_url):
        return {"status": "ok", "server_url": server_url}

    async def agents(server_url):
        return {"agents": [{"name": "revenue"}]}

    async def run(agent_name, prompt, **kwargs):
        return {
            "answer": f"{agent_name}: {prompt}",
            "operation_id": "op_1",
            "status": "completed",
            "warnings": [],
            "runtime": {"tasks": [], "evidence": [], "events": [], "telemetry": {}},
        }

    async def operation(operation_id, server_url):
        return {"operation_id": operation_id}

    async def evidence(operation_id, server_url):
        return {"operation_id": operation_id, "evidence": []}

    async def tasks(operation_id, server_url):
        return {"operation_id": operation_id, "tasks": []}

    monkeypatch.setattr(local_server_client, "get_local_agent_server_status", status)
    monkeypatch.setattr(local_server_client, "list_local_server_agents", agents)
    monkeypatch.setattr(local_server_client, "call_local_agent", run)
    monkeypatch.setattr(
        local_server_client, "get_local_server_runtime_operation", operation
    )
    monkeypatch.setattr(
        local_server_client, "get_local_server_operation_evidence", evidence
    )
    monkeypatch.setattr(local_server_client, "get_local_server_operation_tasks", tasks)

    status_result = json.loads(
        (await call_tool("get_local_agent_server_status", {}))[0].text
    )
    agents_result = json.loads((await call_tool("list_local_server_agents", {}))[0].text)
    run_result = json.loads(
        (
            await call_tool(
                "call_local_agent", {"agent_name": "revenue", "prompt": "hello"}
            )
        )[0].text
    )
    operation_result = json.loads(
        (
            await call_tool(
                "get_local_server_runtime_operation", {"operation_id": "op_1"}
            )
        )[0].text
    )
    evidence_result = json.loads(
        (
            await call_tool(
                "get_local_server_operation_evidence", {"operation_id": "op_1"}
            )
        )[0].text
    )
    tasks_result = json.loads(
        (
            await call_tool(
                "get_local_server_operation_tasks", {"operation_id": "op_1"}
            )
        )[0].text
    )

    assert status_result["status"] == "ok"
    assert agents_result["agents"][0]["name"] == "revenue"
    assert run_result["operation_id"] == "op_1"
    assert operation_result["operation_id"] == "op_1"
    assert evidence_result["evidence"] == []
    assert tasks_result["tasks"] == []
