"""Local Agent Server for development-time DbAgent-compatible factories."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import dataclasses
import importlib.util
import inspect
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_file(path: str | Path | None) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f"Environment file not found: {env_path}")
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_factory(agent_path: str | Path, factory_name: str) -> Any:
    path = Path(agent_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    project_root = path.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    module_name = f"_daita_dev_agent_{path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ImportError(f"Failed to load {path.name}: {exc}") from exc

    if not hasattr(module, factory_name):
        available = [
            name
            for name in dir(module)
            if callable(getattr(module, name)) and not name.startswith("_")
        ]
        raise ValueError(
            f"No {factory_name}() in {path.name}. Available factories: {available}"
        )
    return getattr(module, factory_name)


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _accepted_kwargs(
    fn: Any,
    values: dict[str, Any],
    *,
    override_keys: set[str] | None = None,
) -> dict[str, Any]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return {}
    params = sig.parameters
    override_keys = override_keys or set()
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return {key: value for key, value in values.items() if key in override_keys}
    accepted = {}
    for key, value in values.items():
        param = params.get(key)
        if param is None:
            continue
        is_required = param.default is inspect.Parameter.empty
        if not is_required and key not in override_keys:
            continue
        accepted[key] = value
    return accepted


async def call_factory(
    factory: Any,
    *,
    runtime_store: str = "sqlite",
    runtime_store_path: str | Path = ".daita/runtime.sqlite",
    runtime_override_keys: set[str] | None = None,
) -> Any:
    """Call a user factory, passing runtime hints only when it accepts them."""
    kwargs = _accepted_kwargs(
        factory,
        {
            "runtime_store": runtime_store,
            "runtime_store_path": str(runtime_store_path),
            "store": runtime_store,
            "store_path": str(runtime_store_path),
        },
        override_keys=runtime_override_keys,
    )
    return await maybe_await(factory(**kwargs))


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value):
        return _to_jsonable(dataclasses.asdict(value))
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "dict") and callable(value.dict):
        try:
            return _to_jsonable(value.dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {
            key: _to_jsonable(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


def _as_mapping(value: Any) -> dict[str, Any]:
    data = _to_jsonable(value)
    return data if isinstance(data, dict) else {}


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def describe_agent(agent: Any, fallback_name: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    describe = getattr(agent, "describe", None)
    if describe and callable(describe):
        # Async describe methods are handled in LocalAgentServer.describe_agent.
        pass
    data.update(_as_mapping(agent))
    name = _pick(data, "name", "agent_name", default=getattr(agent, "name", None))
    return {
        "name": str(name or fallback_name),
        "type": _pick(data, "type", "agent_type", default="db_agent"),
        "description": _pick(data, "description", "prompt", default=None),
        "metadata": _pick(data, "metadata", default={}) or {},
    }


def normalize_run_result(
    result: Any,
    *,
    fallback_operation_id: str | None = None,
    include_evidence: bool = True,
    include_tasks: bool = True,
    include_telemetry: bool = True,
) -> dict[str, Any]:
    raw = _to_jsonable(result)
    data = raw if isinstance(raw, dict) else {"answer": str(raw)}
    runtime = _pick(data, "runtime", "runtime_result", "_daita_runtime", default={})
    runtime = runtime if isinstance(runtime, dict) else _as_mapping(runtime)

    answer = _pick(
        data,
        "answer",
        "message",
        "output",
        "content",
        "result",
        default="" if raw is None else str(raw),
    )
    operation_id = _pick(
        data,
        "operation_id",
        "operationId",
        "id",
        default=_pick(runtime, "operation_id", "operationId", "id"),
    )
    operation_id = str(operation_id or fallback_operation_id or f"op_{uuid.uuid4().hex}")

    tasks = _list(_pick(runtime, "tasks", default=_pick(data, "tasks", default=[])))
    evidence = _list(
        _pick(runtime, "evidence", default=_pick(data, "evidence", default=[]))
    )
    events = _list(_pick(runtime, "events", default=_pick(data, "events", default=[])))
    telemetry = _pick(runtime, "telemetry", default=_pick(data, "telemetry", default={}))
    if not isinstance(telemetry, dict):
        telemetry = _as_mapping(telemetry)

    return {
        "answer": answer,
        "operation_id": operation_id,
        "status": str(_pick(data, "status", default="completed")),
        "warnings": _list(_pick(data, "warnings", default=[])),
        "runtime": {
            "tasks": tasks if include_tasks else [],
            "evidence": evidence if include_evidence else [],
            "events": events,
            "telemetry": telemetry if include_telemetry else {},
        },
    }


class SQLiteRuntimeStore:
    """Small local JSON ledger for operation inspection.

    This is intentionally independent of any incomplete framework runtime APIs.
    It provides cross-process SQLite persistence for the normalized local server
    state while richer DbRuntime internals can still appear in the JSON payloads.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists operations (
                    operation_id text primary key,
                    agent_name text not null,
                    session_id text,
                    status text not null,
                    prompt text,
                    answer text,
                    warnings_json text not null,
                    runtime_json text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.commit()

    def record_operation(
        self,
        *,
        agent_name: str,
        prompt: str,
        session_id: str | None,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        operation = {
            "operation_id": result["operation_id"],
            "agent_name": agent_name,
            "session_id": session_id,
            "status": result["status"],
            "prompt": prompt,
            "answer": result["answer"],
            "warnings": result.get("warnings", []),
            "runtime": result.get("runtime", {}),
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into operations (
                    operation_id, agent_name, session_id, status, prompt, answer,
                    warnings_json, runtime_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(operation_id) do update set
                    agent_name=excluded.agent_name,
                    session_id=excluded.session_id,
                    status=excluded.status,
                    prompt=excluded.prompt,
                    answer=excluded.answer,
                    warnings_json=excluded.warnings_json,
                    runtime_json=excluded.runtime_json,
                    updated_at=excluded.updated_at
                """,
                (
                    operation["operation_id"],
                    agent_name,
                    session_id,
                    operation["status"],
                    prompt,
                    operation["answer"],
                    json.dumps(operation["warnings"], default=str),
                    json.dumps(operation["runtime"], default=str),
                    now,
                    now,
                ),
            )
            conn.commit()
        return operation

    def _row_to_operation(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "agent_name": row["agent_name"],
            "session_id": row["session_id"],
            "status": row["status"],
            "prompt": row["prompt"],
            "answer": row["answer"],
            "warnings": json.loads(row["warnings_json"] or "[]"),
            "runtime": json.loads(row["runtime_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_operations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from operations order by created_at desc"
            ).fetchall()
        return [self._row_to_operation(row) for row in rows]

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from operations where operation_id = ?", (operation_id,)
            ).fetchone()
        return self._row_to_operation(row) if row else None


class LocalAgentServer:
    def __init__(self, agents: dict[str, Any], runtime_store: SQLiteRuntimeStore):
        self.agents = agents
        self.runtime_store = runtime_store

    async def start_agents(self) -> None:
        for agent in self.agents.values():
            start = getattr(agent, "start", None)
            if callable(start):
                await maybe_await(start())

    async def stop_agents(self) -> None:
        for agent in self.agents.values():
            stop = getattr(agent, "stop", None)
            if callable(stop):
                await maybe_await(stop())

    async def describe_agent(self, name: str) -> dict[str, Any]:
        agent = self.require_agent(name)
        describe = getattr(agent, "describe", None)
        if callable(describe):
            described = await maybe_await(describe())
            if isinstance(_to_jsonable(described), dict):
                base = describe_agent(agent, name)
                base.update(_as_mapping(described))
                base["name"] = str(_pick(base, "name", "agent_name", default=name))
                return base
        return describe_agent(agent, name)

    def require_agent(self, name: str) -> Any:
        if name not in self.agents:
            raise KeyError(name)
        return self.agents[name]

    async def run_agent(
        self,
        name: str,
        *,
        prompt: str,
        session_id: str | None = None,
        include_evidence: bool = True,
        include_tasks: bool = True,
        include_telemetry: bool = True,
    ) -> dict[str, Any]:
        agent = self.require_agent(name)
        runner = getattr(agent, "run_detailed", None) or getattr(agent, "run", None)
        if not callable(runner):
            raise TypeError(
                f"Agent '{name}' is not DbAgent-compatible: no run_detailed() or run()"
            )
        kwargs = _accepted_kwargs(
            runner,
            {
                "prompt": prompt,
                "session_id": session_id,
                "include_evidence": include_evidence,
                "include_tasks": include_tasks,
                "include_telemetry": include_telemetry,
            },
            override_keys={
                "prompt",
                "session_id",
                "include_evidence",
                "include_tasks",
                "include_telemetry",
            },
        )
        if "prompt" in kwargs:
            result = runner(**kwargs)
        else:
            positional_kwargs = {
                key: value for key, value in kwargs.items() if key != "prompt"
            }
            result = runner(prompt, **positional_kwargs)
        result = await maybe_await(result)
        normalized = normalize_run_result(
            result,
            include_evidence=include_evidence,
            include_tasks=include_tasks,
            include_telemetry=include_telemetry,
        )
        self.runtime_store.record_operation(
            agent_name=name,
            prompt=prompt,
            session_id=session_id,
            result=normalized,
        )
        return normalized


async def build_local_server(
    *,
    agent_path: str | Path,
    factory_name: str = "create_agent",
    runtime_store_path: str | Path = ".daita/runtime.sqlite",
    runtime_store: str = "sqlite",
    env_file: str | Path | None = None,
    runtime_override_keys: set[str] | None = None,
) -> LocalAgentServer:
    if runtime_store != "sqlite":
        raise ValueError("Phase 0 supports only --runtime-store sqlite")

    load_env_file(env_file)
    store = SQLiteRuntimeStore(runtime_store_path)
    factory = load_factory(agent_path, factory_name)
    agent = await call_factory(
        factory,
        runtime_store=runtime_store,
        runtime_store_path=store.path,
        runtime_override_keys=runtime_override_keys,
    )
    fallback_name = Path(agent_path).stem
    name = str(getattr(agent, "name", None) or fallback_name)
    server = LocalAgentServer({name: agent}, store)
    await server.start_agents()
    return server


def create_app(local_server: LocalAgentServer) -> Any:
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
    except ImportError as exc:
        raise RuntimeError(
            "daita dev requires starlette and uvicorn. Install daita-cli with dev server dependencies."
        ) from exc

    async def _shutdown() -> None:
        await local_server.stop_agents()

    @asynccontextmanager
    async def _lifespan(app):
        yield
        await _shutdown()

    async def health(request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "agents": list(local_server.agents.keys()),
                "runtime_store": {
                    "type": "sqlite",
                    "path": str(local_server.runtime_store.path),
                },
            }
        )

    async def list_agents(request) -> JSONResponse:
        agents = [
            await local_server.describe_agent(name)
            for name in sorted(local_server.agents.keys())
        ]
        return JSONResponse({"agents": agents, "count": len(agents)})

    async def get_agent(request) -> JSONResponse:
        agent_name = request.path_params["agent_name"]
        try:
            return JSONResponse(await local_server.describe_agent(agent_name))
        except KeyError:
            return JSONResponse({"detail": "Agent not found"}, status_code=404)

    async def run_agent(request) -> JSONResponse:
        agent_name = request.path_params["agent_name"]
        body = await request.json()
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            return JSONResponse({"detail": "prompt is required"}, status_code=422)
        try:
            return JSONResponse(
                await local_server.run_agent(
                    agent_name,
                    prompt=prompt,
                    session_id=body.get("session_id"),
                    include_evidence=body.get("include_evidence", True),
                    include_tasks=body.get("include_tasks", True),
                    include_telemetry=body.get("include_telemetry", True),
                )
            )
        except KeyError:
            return JSONResponse({"detail": "Agent not found"}, status_code=404)
        except Exception as exc:
            return JSONResponse({"detail": str(exc)}, status_code=500)

    async def list_operations(request) -> JSONResponse:
        operations = local_server.runtime_store.list_operations()
        return JSONResponse({"operations": operations, "count": len(operations)})

    async def get_operation(request) -> JSONResponse:
        operation_id = request.path_params["operation_id"]
        operation = local_server.runtime_store.get_operation(operation_id)
        if not operation:
            return JSONResponse({"detail": "Operation not found"}, status_code=404)
        return JSONResponse(operation)

    async def get_operation_tasks(request) -> JSONResponse:
        operation_id = request.path_params["operation_id"]
        operation = local_server.runtime_store.get_operation(operation_id)
        if not operation:
            return JSONResponse({"detail": "Operation not found"}, status_code=404)
        return JSONResponse(
            {
                "operation_id": operation_id,
                "tasks": _list(operation.get("runtime", {}).get("tasks")),
            }
        )

    async def get_operation_evidence(request) -> JSONResponse:
        operation_id = request.path_params["operation_id"]
        operation = local_server.runtime_store.get_operation(operation_id)
        if not operation:
            return JSONResponse({"detail": "Operation not found"}, status_code=404)
        return JSONResponse(
            {
                "operation_id": operation_id,
                "evidence": _list(operation.get("runtime", {}).get("evidence")),
            }
        )

    return Starlette(
        debug=False,
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/agents", list_agents, methods=["GET"]),
            Route("/agents/{agent_name}", get_agent, methods=["GET"]),
            Route("/agents/{agent_name}/runs", run_agent, methods=["POST"]),
            Route("/runtime/operations", list_operations, methods=["GET"]),
            Route(
                "/runtime/operations/{operation_id}",
                get_operation,
                methods=["GET"],
            ),
            Route(
                "/runtime/operations/{operation_id}/tasks",
                get_operation_tasks,
                methods=["GET"],
            ),
            Route(
                "/runtime/operations/{operation_id}/evidence",
                get_operation_evidence,
                methods=["GET"],
            ),
        ],
        lifespan=_lifespan,
    )


def serve_dev_server(
    *,
    agent_path: str | Path,
    factory_name: str = "create_agent",
    host: str = "127.0.0.1",
    port: int = 8123,
    runtime_store: str = "sqlite",
    runtime_store_path: str | Path = ".daita/runtime.sqlite",
    env_file: str | Path | None = None,
    runtime_override_keys: set[str] | None = None,
) -> None:
    if runtime_store != "sqlite":
        raise ValueError("Phase 0 supports only --runtime-store sqlite")
    server = asyncio.run(
        build_local_server(
            agent_path=agent_path,
            factory_name=factory_name,
            runtime_store=runtime_store,
            runtime_store_path=runtime_store_path,
            env_file=env_file,
            runtime_override_keys=runtime_override_keys,
        )
    )
    app = create_app(server)
    names = ", ".join(server.agents.keys()) or "(none)"
    print(f"Daita local agent server: http://{host}:{port}")
    print(f"Loaded agents: {names}")

    import uvicorn

    uvicorn.run(app, host=host, port=port)
