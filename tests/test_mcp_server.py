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
    assert "list_eval_suites" in names
    assert "list_eval_runs" in names
    assert "get_eval_report" in names
    assert "run_eval_suite" in names
    assert "get_local_agent_server_status" in names
    assert "list_local_server_agents" in names
    assert "call_local_agent" in names
    assert "get_local_server_runtime_operation" in names
    assert "get_local_server_operation_evidence" in names
    assert "get_local_server_operation_tasks" in names


@pytest.mark.asyncio
async def test_conversations_fully_removed():
    """Conversations were dropped from both MCP tools and the CLI command surface."""
    tools = await list_tools()
    names = {t.name for t in tools}
    assert not any("conversation" in n.lower() for n in names)

    from daita_cli.main import cli

    assert "conversations" not in cli.commands


@pytest.mark.asyncio
async def test_list_agents_tool(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "agents": [
                        {
                            "id": "a1",
                            "name": "my_agent",
                            "status": "active",
                            "tools": ["large", "metadata"],
                        }
                    ]
                },
            )
        )
        result = await call_tool("list_agents", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "agents" in data
    assert "tools" not in data["agents"][0]


@pytest.mark.asyncio
async def test_list_deployments_tool_returns_only_active(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        route = mock.get("/api/v1/deployments/api-key").mock(
            return_value=httpx.Response(
                200,
                json={
                    "deployments": [
                        {
                            "deployment_id": "dep-active",
                            "status": "active",
                            "deployment_info": {"large": True},
                        },
                        {"deployment_id": "dep-inactive", "status": "inactive"},
                    ],
                    "total_count": 2,
                },
            )
        )
        result = await call_tool("list_deployments", {"limit": 10})

    assert route.calls.last.request.url.params["status"] == "active"
    data = json.loads(result[0].text)
    assert data["total_count"] == 1
    assert data["deployments"][0]["deployment_id"] == "dep-active"
    assert "deployment_info" not in data["deployments"][0]


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
        assert (
            tool_def.needs_framework is False
        ), f"{name} should not require daita-agents"

    # test_agent is the only local tool that needs it.
    assert mcp._REGISTRY["test_agent"].needs_framework is True
    assert mcp._REGISTRY["call_local_agent"].needs_framework is False
    assert mcp._REGISTRY["call_local_agent"].needs_client is False


@pytest.mark.asyncio
async def test_local_agent_server_mcp_tools(respx_mock):
    base = "http://127.0.0.1:8123"
    respx_mock.get(f"{base}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "agents": ["revenue"]})
    )
    respx_mock.get(f"{base}/agents").mock(
        return_value=httpx.Response(
            200, json={"agents": [{"name": "revenue"}], "count": 1}
        )
    )
    respx_mock.post(f"{base}/agents/revenue/runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "answer": "ok",
                "operation_id": "op_1",
                "status": "completed",
                "warnings": [],
                "runtime": {
                    "tasks": [],
                    "evidence": [],
                    "events": [],
                    "telemetry": {},
                },
            },
        )
    )
    respx_mock.get(f"{base}/runtime/operations/op_1").mock(
        return_value=httpx.Response(200, json={"operation_id": "op_1"})
    )
    respx_mock.get(f"{base}/runtime/operations/op_1/evidence").mock(
        return_value=httpx.Response(
            200, json={"operation_id": "op_1", "evidence": []}
        )
    )
    respx_mock.get(f"{base}/runtime/operations/op_1/tasks").mock(
        return_value=httpx.Response(200, json={"operation_id": "op_1", "tasks": []})
    )

    status = json.loads((await call_tool("get_local_agent_server_status", {}))[0].text)
    agents = json.loads((await call_tool("list_local_server_agents", {}))[0].text)
    run = json.loads(
        (
            await call_tool(
                "call_local_agent", {"agent_name": "revenue", "prompt": "hello"}
            )
        )[0].text
    )
    operation = json.loads(
        (
            await call_tool(
                "get_local_server_runtime_operation", {"operation_id": "op_1"}
            )
        )[0].text
    )
    evidence = json.loads(
        (
            await call_tool(
                "get_local_server_operation_evidence", {"operation_id": "op_1"}
            )
        )[0].text
    )
    tasks = json.loads(
        (
            await call_tool(
                "get_local_server_operation_tasks", {"operation_id": "op_1"}
            )
        )[0].text
    )

    assert status["status"] == "ok"
    assert agents["agents"][0]["name"] == "revenue"
    assert run["operation_id"] == "op_1"
    assert operation["operation_id"] == "op_1"
    assert evidence["evidence"] == []
    assert tasks["tasks"] == []


@pytest.mark.asyncio
async def test_run_agent_emits_progress(monkeypatch):
    """run_agent should poll with backoff and complete when status reaches terminal."""
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.post("/api/v1/executions/execute").mock(
            return_value=httpx.Response(200, json={"execution_id": "exec-123"})
        )
        # First poll → running, second poll → completed
        mock.get("/api/v1/executions/exec-123").mock(
            side_effect=[
                httpx.Response(
                    200, json={"status": "running", "execution_id": "exec-123"}
                ),
                httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "execution_id": "exec-123",
                        "result": "ok",
                    },
                ),
            ]
        )
        result = await call_tool(
            "run_agent",
            {
                "target_name": "my_agent",
                "timeout_seconds": 30,
            },
        )
    data = json.loads(result[0].text)
    assert data["status"] == "completed"
    assert data["result"] == "ok"


@pytest.mark.asyncio
async def test_run_agent_timeout_raises(monkeypatch):
    """run_agent raises TimeoutError if execution doesn't reach a terminal state."""
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.post("/api/v1/executions/execute").mock(
            return_value=httpx.Response(200, json={"execution_id": "exec-456"})
        )
        mock.get("/api/v1/executions/exec-456").mock(
            return_value=httpx.Response(
                200, json={"status": "running", "execution_id": "exec-456"}
            )
        )
        with pytest.raises(TimeoutError, match="exec-456"):
            await call_tool(
                "run_agent",
                {
                    "target_name": "my_agent",
                    "timeout_seconds": 2,  # short so the test finishes fast
                },
            )


@pytest.mark.asyncio
async def test_list_eval_suites_tool(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/evals/suites").mock(
            return_value=httpx.Response(
                200,
                json={
                    "suites": [
                        {
                            "eval_suite_id": "suite-1",
                            "name": "sales",
                            "environment": "production",
                            "config_json": {"large": True},
                        }
                    ],
                    "total_count": 1,
                },
            )
        )
        result = await call_tool("list_eval_suites", {"project_name": "demo"})
    data = json.loads(result[0].text)
    assert data["suites"][0]["name"] == "sales"
    assert "config_json" not in data["suites"][0]


@pytest.mark.asyncio
async def test_get_eval_report_tool(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/evals/runs/run-1/report").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "failed",
                    "suite": {"name": "sales"},
                    "failures": [{"case_id": "top-products"}],
                    "cases": [{"case_id": "large"}],
                },
            )
        )
        result = await call_tool("get_eval_report", {"eval_run_id": "run-1"})
    data = json.loads(result[0].text)
    assert data["suite"]["name"] == "sales"
    assert data["failures"][0]["case_id"] == "top-products"
    assert "cases" not in data


@pytest.mark.asyncio
async def test_get_trace_spans_summarizes_and_limits(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/traces/traces/trace-1/spans").mock(
            return_value=httpx.Response(
                200,
                json={
                    "spans": [
                        {
                            "span_id": "span-1",
                            "name": "agent_run",
                            "duration_ms": 100,
                            "attributes": {"large": True},
                        },
                        {
                            "span_id": "span-2",
                            "name": "llm_call",
                            "duration_ms": 50,
                        },
                    ]
                },
            )
        )
        result = await call_tool("get_trace_spans", {"trace_id": "trace-1", "limit": 1})
    data = json.loads(result[0].text)
    assert data["count"] == 1
    assert data["total_count"] == 2
    assert data["truncated"] is True
    assert "attributes" not in data["spans"][0]


@pytest.mark.asyncio
async def test_get_workspace_memory_defaults_to_smaller_limit(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        route = mock.get("/api/v1/memory/workspaces/main").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await call_tool(
            "get_workspace_memory", {"workspace": "main", "project": "demo"}
        )
    assert route.calls.last.request.url.params["limit"] == "20"


@pytest.mark.asyncio
async def test_run_eval_suite_polls_and_returns_report(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.post("/api/v1/evals/runs/execute").mock(
            return_value=httpx.Response(
                200,
                json={
                    "execution_id": "exec-eval-1",
                    "eval_suite_id": "suite-1",
                    "project_name": "demo",
                },
            )
        )
        mock.get("/api/v1/executions/exec-eval-1").mock(
            return_value=httpx.Response(
                200,
                json={"status": "completed", "execution_id": "exec-eval-1"},
            )
        )
        mock.get("/api/v1/evals/runs").mock(
            return_value=httpx.Response(
                200,
                json={"runs": [{"eval_run_id": "run-1"}], "total_count": 1},
            )
        )
        mock.get("/api/v1/evals/runs/run-1/report").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "failed",
                    "suite": {"name": "sales"},
                    "cases": [{"id": "case-1", "status": "passed"}],
                    "failures": [{"case_id": "case-2", "message": "expected match"}],
                },
            )
        )
        result = await call_tool(
            "run_eval_suite",
            {"eval_suite_id": "suite-1", "timeout_seconds": 30},
        )
    data = json.loads(result[0].text)
    assert data["status"] == "failed"
    assert data["suite"]["name"] == "sales"
    assert data["failures"] == [{"case_id": "case-2", "message": "expected match"}]
    assert "cases" not in data
