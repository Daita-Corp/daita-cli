"""
daita doctor — diagnose setup and connectivity.

Structured around independent `Check` functions that each return a
CheckResult. The runner aggregates results, the renderer formats them.
Keeps the surface scriptable (exit codes, JSON, check IDs) without
sacrificing pretty TTY output.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable

import click
import httpx

from daita_cli import __version__
from daita_cli.api_client import DaitaAPIClient, APIError, AuthError
from daita_cli.output import OutputFormatter


# ---------------------------------------------------------------------------
# Check model
# ---------------------------------------------------------------------------


class Level(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    INFO = "info"

    @property
    def icon(self) -> str:
        return {"ok": "✓", "warn": "⚠", "error": "✗", "info": "•"}[self.value]


@dataclass
class CheckResult:
    id: str
    category: str   # "env" | "platform" | "sources"
    label: str
    level: Level
    message: str = ""
    fix: str | None = None
    fixable: bool = False       # True if --fix can auto-remediate
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["level"] = self.level.value
        return d


CheckFn = Callable[[], Awaitable[CheckResult]]


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------


async def check_python_version() -> CheckResult:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 11)
    return CheckResult(
        id="env.python.version",
        category="env",
        label="Python version",
        level=Level.OK if ok else Level.ERROR,
        message=f"{major}.{minor}.{sys.version_info.micro}",
        fix=None if ok else "Install Python 3.11 or later.",
        details={"required": "3.11+", "found": f"{major}.{minor}"},
    )


async def check_cli_version() -> CheckResult:
    return CheckResult(
        id="env.cli.version",
        category="env",
        label="daita-cli version",
        level=Level.INFO,
        message=__version__,
        details={"version": __version__},
    )


async def check_api_key() -> CheckResult:
    key = os.getenv("DAITA_API_KEY")
    if not key:
        return CheckResult(
            id="env.api_key.missing",
            category="env",
            label="DAITA_API_KEY",
            level=Level.ERROR,
            message="not set",
            fix="export DAITA_API_KEY=<your-key>  (get one at daita-tech.io/settings/api-keys)",
        )
    if not (key.startswith("sk-") or key.startswith("daita_")) or len(key) < 16:
        return CheckResult(
            id="env.api_key.malformed",
            category="env",
            label="DAITA_API_KEY",
            level=Level.WARN,
            message="present but format is unusual",
            details={"length": len(key), "prefix": key[:3]},
        )
    return CheckResult(
        id="env.api_key.ok",
        category="env",
        label="DAITA_API_KEY",
        level=Level.OK,
        message=f"set ({len(key)} chars)",
    )


async def check_framework() -> CheckResult:
    try:
        import daita.agents  # noqa: F401
        import importlib.metadata
        try:
            version = importlib.metadata.version("daita-agents")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return CheckResult(
            id="env.framework.ok",
            category="env",
            label="daita-agents",
            level=Level.OK,
            message=f"installed ({version})",
            details={"version": version},
        )
    except ImportError:
        return CheckResult(
            id="env.framework.missing",
            category="env",
            label="daita-agents",
            level=Level.WARN,
            message="not installed (only required for init/create/test/push)",
            fix="pip install daita-agents",
            fixable=True,
        )


# ---------------------------------------------------------------------------
# Platform checks
# ---------------------------------------------------------------------------


async def check_api_connectivity(timeout: float = 5.0) -> CheckResult:
    base = os.getenv("DAITA_API_ENDPOINT", "https://api.daita-tech.io").rstrip("/")
    import time
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            t0 = time.monotonic()
            resp = await c.get(f"{base}/health")
            latency_ms = (time.monotonic() - t0) * 1000
    except httpx.TimeoutException:
        return CheckResult(
            id="platform.api.timeout",
            category="platform",
            label="API connectivity",
            level=Level.ERROR,
            message=f"timed out after {timeout:.0f}s reaching {base}",
            fix="Check network, or set DAITA_API_ENDPOINT to the correct region.",
        )
    except Exception as e:
        return CheckResult(
            id="platform.api.unreachable",
            category="platform",
            label="API connectivity",
            level=Level.ERROR,
            message=f"unreachable: {e}",
            details={"endpoint": base},
        )

    if resp.status_code >= 500:
        return CheckResult(
            id="platform.api.5xx",
            category="platform",
            label="API connectivity",
            level=Level.ERROR,
            message=f"HTTP {resp.status_code} from {base}",
            details={"endpoint": base, "status": resp.status_code},
        )
    return CheckResult(
        id="platform.api.ok",
        category="platform",
        label="API connectivity",
        level=Level.OK,
        message=f"{base} reachable ({latency_ms:.0f}ms)",
        details={"endpoint": base, "latency_ms": round(latency_ms, 1)},
    )


async def check_auth() -> CheckResult:
    """Verify the API key actually authenticates (not just set)."""
    try:
        async with DaitaAPIClient() as client:
            # Lightweight authenticated endpoint — list 1 agent.
            await client.get("/api/v1/agents/agents", params={"per_page": 1})
    except AuthError as e:
        return CheckResult(
            id="platform.auth.invalid",
            category="platform",
            label="API authentication",
            level=Level.ERROR,
            message="API key rejected by server",
            fix="Verify DAITA_API_KEY at daita-tech.io/settings/api-keys",
            details={"detail": str(e)},
        )
    except APIError as e:
        return CheckResult(
            id="platform.auth.api_error",
            category="platform",
            label="API authentication",
            level=Level.WARN,
            message=f"could not verify: {e}",
            details={"status_code": e.status_code},
        )
    except Exception as e:
        return CheckResult(
            id="platform.auth.error",
            category="platform",
            label="API authentication",
            level=Level.WARN,
            message=f"could not verify: {e}",
        )
    return CheckResult(
        id="platform.auth.ok",
        category="platform",
        label="API authentication",
        level=Level.OK,
        message="API key authenticates successfully",
    )


async def check_project_config() -> CheckResult:
    cfg = Path.cwd() / "daita-project.yaml"
    if not cfg.exists():
        return CheckResult(
            id="platform.project.none",
            category="platform",
            label="Project config",
            level=Level.INFO,
            message="no daita-project.yaml in current directory (ok if not in a project)",
        )
    try:
        import yaml
        with cfg.open() as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        return CheckResult(
            id="platform.project.invalid",
            category="platform",
            label="Project config",
            level=Level.ERROR,
            message=f"daita-project.yaml is invalid: {e}",
            fix="Run `daita init` to scaffold a fresh config, or fix the YAML.",
        )
    return CheckResult(
        id="platform.project.ok",
        category="platform",
        label="Project config",
        level=Level.OK,
        message=(
            f"{data.get('name', '(unnamed)')} — "
            f"{len(data.get('agents', []))} agents, {len(data.get('workflows', []))} workflows"
        ),
        details={"path": str(cfg), "name": data.get("name")},
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


ENV_CHECKS: tuple[CheckFn, ...] = (
    check_python_version,
    check_cli_version,
    check_api_key,
    check_framework,
)

PLATFORM_CHECKS: tuple[CheckFn, ...] = (
    check_api_connectivity,
    check_auth,
    check_project_config,
)


async def _run_checks(checks: tuple[CheckFn, ...], per_check_timeout: float) -> list[CheckResult]:
    async def _guarded(fn: CheckFn) -> CheckResult:
        try:
            return await asyncio.wait_for(fn(), timeout=per_check_timeout)
        except asyncio.TimeoutError:
            return CheckResult(
                id=f"check.timeout.{fn.__name__}",
                category="platform",
                label=fn.__name__,
                level=Level.ERROR,
                message=f"check exceeded {per_check_timeout:.0f}s timeout",
            )
        except Exception as e:
            return CheckResult(
                id=f"check.error.{fn.__name__}",
                category="platform",
                label=fn.__name__,
                level=Level.ERROR,
                message=f"check crashed: {e}",
            )

    return await asyncio.gather(*(_guarded(fn) for fn in checks))


async def run_doctor(
    *,
    env: bool = True,
    platform: bool = True,
    sources: bool = False,  # reserved for v2 — connector probes
    per_check_timeout: float = 5.0,
) -> list[CheckResult]:
    """Run the selected check groups and return all results."""
    bundles: list[CheckResult] = []
    if env:
        bundles.extend(await _run_checks(ENV_CHECKS, per_check_timeout))
    if platform:
        bundles.extend(await _run_checks(PLATFORM_CHECKS, per_check_timeout))
    return bundles


# ---------------------------------------------------------------------------
# Auto-fix (scoped — only installs packages with user consent)
# ---------------------------------------------------------------------------


async def _attempt_fix(result: CheckResult) -> bool:
    """Return True if the fix succeeded. Currently scoped to pip installs only."""
    if not result.fixable:
        return False
    if result.id == "env.framework.missing":
        import subprocess
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "daita-agents"])
            return True
        except subprocess.CalledProcessError:
            return False
    return False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_tty(results: list[CheckResult]) -> str:
    lines = [f"daita doctor v{__version__}", "─" * 58]
    by_cat: dict[str, list[CheckResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    for cat in ("env", "platform", "sources"):
        if cat not in by_cat:
            continue
        lines.append(cat.capitalize())
        for r in by_cat[cat]:
            lines.append(f"  {r.level.icon}  {r.label:<28}  {r.message}")
            if r.fix:
                lines.append(f"       → {r.fix}")
        lines.append("")

    counts = _count(results)
    summary = (
        f"{counts[Level.ERROR]} errors, "
        f"{counts[Level.WARN]} warnings, "
        f"{counts[Level.OK]} ok"
    )
    lines.append(summary)
    lines.append("(note: data-source probes run from this machine; "
                 "cloud-runtime reachability may differ)")
    return "\n".join(lines)


def _count(results: list[CheckResult]) -> dict[Level, int]:
    return {lvl: sum(1 for r in results if r.level == lvl) for lvl in Level}


def _exit_code(results: list[CheckResult], fail_on: Level) -> int:
    counts = _count(results)
    if counts[Level.ERROR] > 0 and fail_on in (Level.ERROR, Level.WARN):
        return 2
    if counts[Level.WARN] > 0 and fail_on == Level.WARN:
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("doctor")
@click.option("--env-only", is_flag=True, help="Only run environment checks.")
@click.option("--platform-only", is_flag=True, help="Only run platform/API checks.")
@click.option("--fail-on", type=click.Choice(["error", "warn"]), default="error",
              show_default=True, help="Exit non-zero if any check is at or above this level.")
@click.option("--fix", is_flag=True, help="Attempt to auto-fix fixable issues (pip installs only).")
@click.option("--timeout", "per_check_timeout", default=5.0, show_default=True, type=float,
              help="Per-check timeout in seconds.")
@click.pass_context
def doctor_command(
    ctx,
    env_only: bool,
    platform_only: bool,
    fail_on: str,
    fix: bool,
    per_check_timeout: float,
):
    """Diagnose daita-cli setup and platform connectivity."""
    formatter: OutputFormatter = (ctx.obj or {}).get("formatter", OutputFormatter())

    run_env = not platform_only
    run_platform = not env_only

    async def _main():
        from daita_cli.commands._spinner import spinner

        async with spinner("Running health checks…", formatter=formatter):
            results = await run_doctor(
                env=run_env,
                platform=run_platform,
                per_check_timeout=per_check_timeout,
            )
        if fix:
            fixable = [r for r in results if r.fixable and r.level in (Level.ERROR, Level.WARN)]
            for r in fixable:
                async with spinner(f"Fixing {r.id}…", formatter=formatter):
                    ok = await _attempt_fix(r)
                r.details["auto_fix_attempted"] = True
                r.details["auto_fix_succeeded"] = ok
        return results

    results = asyncio.run(_main())

    if formatter.is_json:
        print(json.dumps({
            "version": __version__,
            "results": [r.as_dict() for r in results],
            "counts": {lvl.value: n for lvl, n in _count(results).items()},
        }, indent=2, default=str))
    else:
        click.echo(_render_tty(results))

    sys.exit(_exit_code(results, Level(fail_on)))
