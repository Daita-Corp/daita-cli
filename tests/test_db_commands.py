import json

from click.testing import CliRunner

from daita_cli import local_server_client
from daita_cli.main import cli


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


def use_fake_client(monkeypatch, responses):
    import daita_cli.command_helpers as command_helpers

    FakeDaitaAPIClient.calls = []
    FakeDaitaAPIClient.responses = responses
    monkeypatch.setattr(command_helpers, "DaitaAPIClient", FakeDaitaAPIClient)
    return FakeDaitaAPIClient


def test_webhooks_command_is_not_registered():
    runner = CliRunner()

    help_result = runner.invoke(cli, ["--help"])
    command_result = runner.invoke(cli, ["webhooks", "list"])

    assert help_result.exit_code == 0
    assert "webhooks" not in cli.commands
    assert "webhooks" not in help_result.output
    assert command_result.exit_code != 0


def test_db_commands_and_dev_alias_are_registered():
    runner = CliRunner()

    db_help = runner.invoke(cli, ["db", "--help"])
    dev_help = runner.invoke(cli, ["db", "dev", "--help"])

    assert db_help.exit_code == 0
    assert "list" in db_help.output
    assert "show" in db_help.output
    assert "refresh" in db_help.output
    assert "ask" in db_help.output
    assert "inspect" in db_help.output
    assert "evidence" in db_help.output
    assert "tasks" in db_help.output
    assert dev_help.exit_code == 0
    assert "--factory" in dev_help.output


def test_db_ask_local_calls_local_server_and_preserves_structured_output(monkeypatch):
    calls = []

    async def run(agent_name, prompt, **kwargs):
        calls.append((agent_name, prompt, kwargs))
        return {
            "answer": "hi",
            "operation_id": "op_1",
            "status": "completed",
            "warnings": ["low confidence"],
            "runtime": {
                "tasks": [{"task_id": "task_1"}],
                "evidence": [{"evidence_id": "ev_1"}],
                "events": [],
                "telemetry": {"model": "test-model"},
            },
        }

    monkeypatch.setattr(local_server_client, "call_local_agent", run)

    result = CliRunner().invoke(
        cli,
        [
            "--output",
            "json",
            "db",
            "ask",
            "revenue",
            "hello",
            "--local",
            "--server-url",
            "http://localhost:9999",
            "--session-id",
            "s1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "revenue",
            "hello",
            {"server_url": "http://localhost:9999", "session_id": "s1"},
        )
    ]
    payload = json.loads(result.output)
    assert payload["answer"] == "hi"
    assert payload["operation_id"] == "op_1"
    assert payload["status"] == "completed"
    assert payload["warnings"] == ["low confidence"]
    assert payload["runtime"]["telemetry"]["model"] == "test-model"
    assert payload["runtime_summary"] == {
        "task_count": 1,
        "evidence_count": 1,
        "event_count": 0,
        "telemetry": {"model": "test-model"},
    }


def test_db_ask_without_local_fails_clearly():
    result = CliRunner().invoke(cli, ["db", "ask", "revenue", "hello"])

    assert result.exit_code != 0
    assert "supports only --local" in result.output


def test_db_inspect_local_calls_agent_detail(monkeypatch):
    calls = []

    async def inspect(agent_name, server_url):
        calls.append((agent_name, server_url))
        return {"name": agent_name, "kind": "db"}

    monkeypatch.setattr(local_server_client, "get_local_server_agent", inspect)

    result = CliRunner().invoke(
        cli,
        [
            "--output",
            "json",
            "db",
            "inspect",
            "revenue",
            "--local",
            "--server-url",
            "http://localhost:9999",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("revenue", "http://localhost:9999")]
    assert json.loads(result.output) == {"name": "revenue", "kind": "db"}


def test_db_evidence_local_calls_operation_evidence(monkeypatch):
    calls = []

    async def evidence(operation_id, server_url):
        calls.append((operation_id, server_url))
        return {"operation_id": operation_id, "evidence": [{"kind": "query.result"}]}

    monkeypatch.setattr(
        local_server_client, "get_local_server_operation_evidence", evidence
    )

    result = CliRunner().invoke(
        cli,
        [
            "--output",
            "json",
            "db",
            "evidence",
            "op_1",
            "--local",
            "--server-url",
            "http://localhost:9999",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("op_1", "http://localhost:9999")]
    assert json.loads(result.output) == {
        "operation_id": "op_1",
        "evidence": [{"kind": "query.result"}],
    }


def test_db_tasks_local_calls_operation_tasks(monkeypatch):
    calls = []

    async def tasks(operation_id, server_url):
        calls.append((operation_id, server_url))
        return {"operation_id": operation_id, "tasks": [{"task_id": "task_1"}]}

    monkeypatch.setattr(local_server_client, "get_local_server_operation_tasks", tasks)

    result = CliRunner().invoke(
        cli,
        [
            "--output",
            "json",
            "db",
            "tasks",
            "op_1",
            "--local",
            "--server-url",
            "http://localhost:9999",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("op_1", "http://localhost:9999")]
    assert json.loads(result.output) == {
        "operation_id": "op_1",
        "tasks": [{"task_id": "task_1"}],
    }


def test_db_list_uses_database_agent_path_and_json_output(monkeypatch):
    fake = use_fake_client(
        monkeypatch,
        {
            "/api/v1/agents/agents/database": {
                "database_agents": [
                    {
                        "agent_id": "db_1",
                        "name": "revenue",
                        "status": "active",
                        "source": {"name": "warehouse"},
                        "catalog": {"status": "fresh"},
                        "large_payload": {"keep": "out of display rows"},
                    }
                ]
            }
        },
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["--output", "json", "db", "list"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/agents/agents/database", None)]
    payload = json.loads(result.output)
    assert payload == {
        "items": [
            {
                "id": "db_1",
                "name": "revenue",
                "status": "active",
                "source": "warehouse",
                "catalog_freshness": "fresh",
            }
        ],
        "count": 1,
    }


def test_db_list_text_and_table_output(monkeypatch):
    runner = CliRunner()

    for output_mode in ("text", "table"):
        use_fake_client(
            monkeypatch,
            {
                "/api/v1/agents/agents/database": {
                    "agents": [{"id": "db_1", "name": "revenue"}]
                }
            },
        )
        result = runner.invoke(cli, ["--output", output_mode, "db", "list"])

        assert result.exit_code == 0, result.output
        assert "Database Agents (1)" in result.output
        assert "DB_1" not in result.output
        assert "db_1" in result.output
        assert "revenue" in result.output


def test_db_show_uses_database_agent_detail_path(monkeypatch):
    fake = use_fake_client(
        monkeypatch,
        {"/api/v1/agents/agents/db_1/database": {"id": "db_1", "name": "revenue"}},
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["--output", "json", "db", "show", "db_1"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/agents/agents/db_1/database", None)]
    assert json.loads(result.output) == {"id": "db_1", "name": "revenue"}


def test_db_refresh_uses_database_agent_refresh_path_and_post(monkeypatch):
    fake = use_fake_client(
        monkeypatch,
        {
            "/api/v1/agents/agents/db_1/database/refresh": {
                "status": "refreshing",
                "agent_id": "db_1",
            }
        },
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["--output", "json", "db", "refresh", "db_1"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("POST", "/api/v1/agents/agents/db_1/database/refresh", None)
    ]
    payload = json.loads(result.output)
    assert payload == {
        "status": "ok",
        "data": {"status": "refreshing", "agent_id": "db_1"},
    }
