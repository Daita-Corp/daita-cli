from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner

from daita_cli.local_agent_server import (
    LocalAgentServer,
    SQLiteRuntimeStore,
    build_local_server,
    call_factory,
    create_app,
    normalize_run_result,
)
from daita_cli.local_server_client import (
    LocalAgentServerClient,
    call_local_agent,
    get_local_agent_server_status,
    get_local_server_operation_evidence,
    get_local_server_operation_tasks,
    get_local_server_runtime_operation,
    list_local_server_agents,
)
from daita_cli.main import cli
from daita_cli import local_server_client


class FakeDbAgent:
    name = "revenue"

    def describe(self):
        return {
            "name": self.name,
            "type": "db_agent",
            "description": "Revenue analysis",
        }

    async def run_detailed(
        self,
        prompt,
        session_id=None,
        include_evidence=True,
        include_tasks=True,
        include_telemetry=True,
    ):
        return {
            "answer": f"answered: {prompt}",
            "operation_id": "op_test",
            "status": "completed",
            "runtime": {
                "tasks": [{"task_id": "task_1", "status": "completed"}],
                "evidence": [{"evidence_id": "ev_1", "kind": "query.result"}],
                "events": [{"type": "completed"}],
                "telemetry": {"model": "test-model"},
            },
        }


@pytest.fixture
def local_server(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / ".daita" / "runtime.sqlite")
    return LocalAgentServer({"revenue": FakeDbAgent()}, store)


@pytest.mark.asyncio
async def test_local_server_health_agents_run_and_runtime_endpoints(local_server):
    app = create_app(local_server)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        health = (await client.get("/health")).json()
        agents = (await client.get("/agents")).json()
        run = (
            await client.post(
                "/agents/revenue/runs",
                json={
                    "prompt": "What changed?",
                    "session_id": "s1",
                    "include_evidence": True,
                    "include_tasks": True,
                    "include_telemetry": True,
                },
            )
        ).json()
        operation = (await client.get("/runtime/operations/op_test")).json()
        tasks = (await client.get("/runtime/operations/op_test/tasks")).json()
        evidence = (await client.get("/runtime/operations/op_test/evidence")).json()

    assert health["status"] == "ok"
    assert health["agents"] == ["revenue"]
    assert agents["agents"][0]["name"] == "revenue"
    assert run["answer"] == "answered: What changed?"
    assert run["operation_id"] == "op_test"
    assert run["runtime"]["tasks"][0]["task_id"] == "task_1"
    assert operation["session_id"] == "s1"
    assert operation["runtime"]["telemetry"]["model"] == "test-model"
    assert tasks == {
        "operation_id": "op_test",
        "tasks": [{"task_id": "task_1", "status": "completed"}],
    }
    assert evidence == {
        "operation_id": "op_test",
        "evidence": [{"evidence_id": "ev_1", "kind": "query.result"}],
    }


def test_runtime_normalization_returns_stable_empty_shapes():
    result = normalize_run_result(SimpleNamespace(answer="ok", operation_id="op_1"))

    assert result == {
        "answer": "ok",
        "operation_id": "op_1",
        "status": "completed",
        "warnings": [],
        "runtime": {"tasks": [], "evidence": [], "events": [], "telemetry": {}},
    }


@pytest.mark.asyncio
async def test_build_local_server_creates_runtime_store_and_passes_required_options(
    tmp_path, monkeypatch
):
    agent_file = tmp_path / "agents" / "revenue.py"
    agent_file.parent.mkdir()
    agent_file.write_text(
        """
class Agent:
    name = "factory-agent"
    def __init__(self, path):
        self.path = path
    async def run_detailed(self, prompt):
        return {"answer": self.path, "operation_id": "op_factory"}

async def create_agent(runtime_store_path):
    return Agent(runtime_store_path)
"""
    )
    monkeypatch.chdir(tmp_path)

    server = await build_local_server(
        agent_path=agent_file,
        factory_name="create_agent",
        runtime_store_path=".daita/runtime.sqlite",
    )

    assert (tmp_path / ".daita" / "runtime.sqlite").exists()
    assert list(server.agents) == ["factory-agent"]
    run = await server.run_agent("factory-agent", prompt="hello")
    assert run["answer"].endswith(".daita/runtime.sqlite")


@pytest.mark.asyncio
async def test_factory_runtime_options_preserve_optional_defaults_unless_overridden(
    tmp_path,
):
    def create_agent(runtime_store_path="factory-default"):
        return SimpleNamespace(name="agent", path=runtime_store_path)

    default_agent = await call_factory(
        create_agent,
        runtime_store_path=tmp_path / ".daita" / "runtime.sqlite",
    )
    override_agent = await call_factory(
        create_agent,
        runtime_store_path=tmp_path / ".daita" / "runtime.sqlite",
        runtime_override_keys={"runtime_store_path"},
    )

    assert default_agent.path == "factory-default"
    assert str(override_agent.path).endswith(".daita/runtime.sqlite")


def test_dev_command_help_and_db_alias_are_registered():
    runner = CliRunner()

    dev_help = runner.invoke(cli, ["dev", "--help"])
    db_help = runner.invoke(cli, ["db", "dev", "--help"])

    assert dev_help.exit_code == 0
    assert "--agent" in dev_help.output
    assert "--runtime-store-path" in dev_help.output
    assert db_help.exit_code == 0
    assert "--factory" in db_help.output


def test_dev_command_rejects_non_sqlite_runtime_store():
    result = CliRunner().invoke(
        cli,
        ["dev", "--agent", "agents/revenue.py", "--runtime-store", "postgres"],
    )

    assert result.exit_code != 0
    assert "Phase 0 supports only sqlite" in result.output


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAsyncClient:
    calls = []
    responses = {
        ("GET", "/health"): {"status": "ok"},
        ("GET", "/agents"): {"agents": []},
        (
            "POST",
            "/agents/revenue/runs",
        ): {
            "answer": "ok",
            "operation_id": "op_1",
            "status": "completed",
            "warnings": [],
            "runtime": {"tasks": [], "evidence": [], "events": [], "telemetry": {}},
        },
        ("GET", "/runtime/operations/op_1"): {"operation_id": "op_1"},
        ("GET", "/runtime/operations/op_1/tasks"): {
            "operation_id": "op_1",
            "tasks": [],
        },
        ("GET", "/runtime/operations/op_1/evidence"): {
            "operation_id": "op_1",
            "evidence": [],
        },
        ("GET", "/agents/revenue"): {"name": "revenue"},
    }

    def __init__(self, base_url, timeout):
        self.base_url = base_url
        self.timeout = timeout

    async def aclose(self):
        return None

    async def get(self, path):
        self.calls.append(("GET", path))
        return FakeResponse(self.responses[("GET", path)])

    async def post(self, path, json):
        self.calls.append(("POST", path, json))
        return FakeResponse(self.responses[("POST", path)])


@pytest.mark.asyncio
async def test_local_client_helper_paths(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr(local_server_client.httpx, "AsyncClient", FakeAsyncClient)

    assert await get_local_agent_server_status() == {"status": "ok"}
    assert await list_local_server_agents() == {"agents": []}
    assert (await call_local_agent("revenue", "hi"))["operation_id"] == "op_1"
    assert await get_local_server_runtime_operation("op_1") == {"operation_id": "op_1"}
    assert await get_local_server_operation_tasks("op_1") == {
        "operation_id": "op_1",
        "tasks": [],
    }
    assert await get_local_server_operation_evidence("op_1") == {
        "operation_id": "op_1",
        "evidence": [],
    }
    assert ("GET", "/health") in FakeAsyncClient.calls
    assert ("POST", "/agents/revenue/runs", {
        "prompt": "hi",
        "session_id": None,
        "include_evidence": True,
        "include_tasks": True,
        "include_telemetry": True,
    }) in FakeAsyncClient.calls


@pytest.mark.asyncio
async def test_local_client_context_manager_get_agent_path(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr(local_server_client.httpx, "AsyncClient", FakeAsyncClient)

    async with LocalAgentServerClient() as client:
        assert await client.get_agent("revenue") == {"name": "revenue"}

    assert ("GET", "/agents/revenue") in FakeAsyncClient.calls
