"""Tests for MCP server tool handlers."""

import json
import pytest
import respx
import httpx

from daita_cli.mcp_server import call_tool, list_tools
from daita_cli.api_client import AuthError


@pytest.mark.asyncio
async def test_list_tools_returns_all():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "list_agents" in names
    assert "run_agent" in names
    assert "get_trace" in names
    assert "list_secrets" in names
    assert "init_project" in names


@pytest.mark.asyncio
async def test_list_tools_excludes_conversations():
    """Conversations were removed from MCP surface (CLI-only)."""
    tools = await list_tools()
    names = {t.name for t in tools}
    assert not any(n.endswith("_conversation") or n == "list_conversations" for n in names)


@pytest.mark.asyncio
async def test_list_agents_tool(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents").mock(
            return_value=httpx.Response(200, json={"agents": [{"id": "a1", "name": "my_agent"}]})
        )
        result = await call_tool("list_agents", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "agents" in data


@pytest.mark.asyncio
async def test_missing_api_key_raises():
    """Errors raise — the MCP SDK wraps them as isError results."""
    import os
    old = os.environ.pop("DAITA_API_KEY", None)
    try:
        with pytest.raises(AuthError):
            await call_tool("list_agents", {})
    finally:
        if old:
            os.environ["DAITA_API_KEY"] = old


@pytest.mark.asyncio
async def test_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("nonexistent_tool", {})


@pytest.mark.asyncio
async def test_test_agent_without_framework_raises(monkeypatch):
    """test_agent must fail loudly when daita-agents is not installed."""
    import daita_cli.mcp_server as mcp

    monkeypatch.setattr(mcp, "_framework_available", lambda: False)
    with pytest.raises(RuntimeError, match="daita-agents"):
        await call_tool("test_agent", {})


@pytest.mark.asyncio
async def test_local_tools_do_not_require_framework(monkeypatch):
    """init_project / create_agent / create_workflow should NOT require daita-agents.

    They only write template files; the generated code imports daita at user runtime.
    """
    import daita_cli.mcp_server as mcp

    monkeypatch.setattr(mcp, "_framework_available", lambda: False)

    # We don't actually run these (they'd touch the filesystem), we just confirm
    # the framework guard doesn't trip. Look them up in the registry directly.
    for name in ("init_project", "create_agent", "create_workflow"):
        tool_def = mcp._REGISTRY[name]
        assert tool_def.needs_framework is False, f"{name} should not require daita-agents"

    # test_agent is the only local tool that needs it.
    assert mcp._REGISTRY["test_agent"].needs_framework is True


@pytest.mark.asyncio
async def test_run_agent_emits_progress(monkeypatch):
    """run_agent should poll with backoff and complete when status reaches terminal."""
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.post("/api/v1/autonomous/execute").mock(
            return_value=httpx.Response(200, json={"execution_id": "exec-123"})
        )
        # First poll → running, second poll → completed
        mock.get("/api/v1/autonomous/executions/exec-123").mock(
            side_effect=[
                httpx.Response(200, json={"status": "running", "execution_id": "exec-123"}),
                httpx.Response(200, json={"status": "completed", "execution_id": "exec-123", "result": "ok"}),
            ]
        )
        result = await call_tool("run_agent", {
            "target_name": "my_agent",
            "timeout_seconds": 30,
        })
    data = json.loads(result[0].text)
    assert data["status"] == "completed"
    assert data["result"] == "ok"


@pytest.mark.asyncio
async def test_run_agent_timeout_raises(monkeypatch):
    """run_agent raises TimeoutError if execution doesn't reach a terminal state."""
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.post("/api/v1/autonomous/execute").mock(
            return_value=httpx.Response(200, json={"execution_id": "exec-456"})
        )
        mock.get("/api/v1/autonomous/executions/exec-456").mock(
            return_value=httpx.Response(200, json={"status": "running", "execution_id": "exec-456"})
        )
        with pytest.raises(TimeoutError, match="exec-456"):
            await call_tool("run_agent", {
                "target_name": "my_agent",
                "timeout_seconds": 2,  # short so the test finishes fast
            })
