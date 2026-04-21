# Changelog

All notable changes to `daita-cli` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-04-20

First feature release after the standalone-repo split from `daita-agents`.
Focus: iteration loop commands (replay, diff), diagnostics, better observability,
and a robust foundation against backend field-name drift.

### Added

- **`daita replay <execution_id>`** — re-run a past execution with identical
  inputs. Never mutates the original; returns a new execution tagged
  `replay_of=<id>`. Supports `--deployment` (replay against a different
  deployment version), `--override` (JSON patch), `--follow`, `--timeout`,
  and `--diff` to automatically compare against the original on completion.
- **`daita diff <exec_a> <exec_b>`** — compare two executions across status,
  duration, cost, tokens, output, span timings, and decisions. `--focus`
  narrows to one dimension (`all`, `output`, `spans`, `decisions`, `cost`);
  `--unified` prints a git-style output diff. Exits `1` when statuses
  diverge, for CI promotion gates.
- **`daita doctor`** — environment and platform health diagnostics with
  structured exit codes (`0` clean, `1` warn-only, `2` errors), copy-pasteable
  fix hints, stable per-check IDs for machine consumption, `--env-only` /
  `--platform-only` / `--fail-on error|warn` flags, per-check `--timeout`,
  and a scoped `--fix` that only auto-installs missing framework packages.
- **ASCII timeline** in `daita traces spans` — renders a tree with visual
  duration bars and "⚠ slow" flags on TTY, auto-switches to structured JSON
  with pre-computed bottlenecks when piped. Flags: `--mode timeline|tree|flat`,
  `--ascii` fallback (auto-detects non-UTF locales), `--width`,
  `--min-duration`.
- **`daita create skill <name>`** — new scaffolding command matching the
  existing `create agent` / `create workflow` pattern.
- **Skills folder in `daita init`** — new projects now include a `skills/`
  directory alongside `agents/` and `workflows/`, plus a starter
  `skills/example_skill.py` demonstrating instruction + tool bundling.
  `daita-project.yaml` tracks skills alongside agents and workflows.
- **Progress spinners** on long-running commands (`doctor`, `diff`, `replay`).
  Silently disabled in pipes, JSON mode, and CI contexts. Opt out globally
  via `DAITA_NO_SPINNER=1`.
- **MCP tools**: `replay_execution`, `diff_executions`, `doctor`,
  `get_trace_timeline`, `create_skill`. Server now exposes 35 tools total.
- **MCP progress streaming** — `run_agent` and `replay_execution` now emit
  MCP progress notifications while polling, letting hosts (Claude Code,
  Cursor, Codex) show real-time status during long executions.
- **`DAITA_NO_SPINNER`** environment variable.

### Changed

- **MCP server architecture** — migrated from a central if/elif dispatcher
  to a decorator-based registry. Tool schema and handler now colocate on
  each function; adding a tool is a single-location change.
- **MCP error semantics** — tool handlers now raise exceptions (correctly
  wrapped as `isError=true` by the SDK) instead of returning pseudo-error
  JSON. Clients can now reliably distinguish errors from data.
- **MCP polling backoff** — adaptive backoff (1s → 1.5× → max 5s) replaces
  fixed 1s polling. A 5-minute run drops from ~300 HTTP calls to ~70.
- **`daita executions list` endpoint** — now queries `/api/v1/executions/`
  (all execution sources). Previously queried `/api/v1/autonomous/executions`
  which excluded `execution_source='cli'` runs, leading to confusing empty
  results.
- **List commands tolerate API field drift** — `traces`, `executions`, and
  `agents` list commands now project API responses through stable display
  schemas via shared `pick()` / `normalize_rows()` helpers. camelCase and
  snake_case field names are both accepted, so minor backend renames no
  longer produce empty columns.
- **`daita executions list` ordering** — newest-first, client-side sorted in
  addition to trusting server order.
- **`daita diff` metric lookup** — cost and token counts live on the trace
  record in this backend (not the execution). Diff now falls through from
  execution → trace for metrics, producing populated summaries instead of
  blank rows.
- **`daita diff` decision matching** — the backend `DecisionEvent` model has
  no top-level `id` field. Matching now falls through `decision_id` →
  `decisionId` → `id` → `data.span_id` → composite `(timestamp, decisionPoint)`.
- **Framework-guard descriptions** — `init_project`, `create_agent`, and
  `create_workflow` MCP tools no longer falsely claim to require
  `daita-agents`. Only `test_agent` actually imports user code at runtime
  and needs the framework installed.

### Fixed

- `daita traces spans` rendered "No spans to display" against real API
  payloads because the tree builder didn't recognize camelCase span fields
  (`spanId`, `parentSpanId`, `operationName`, `startTime`).
- `daita traces list` and related list commands rendered empty columns
  because display keys didn't match the API's actual field names.
- MCP `_require_framework_mcp` guard was inconsistently applied — now
  centralized in the dispatcher via a registry flag.

### Removed

- `daita conversations` CLI command and all conversation MCP tools pending
  a redesigned surface. The existing endpoints are still reachable via the
  API directly.
- Dead `→ daita open <id>` nudge in `daita traces spans` output. The
  `daita open` command isn't implemented yet; the nudge was pointing at a
  ghost.
- `rollback_deployment` entry from the README MCP tools table (pre-existing
  documentation bug — the tool was never registered in the MCP server).


---

## [0.1.1] and earlier

Pre-release versions from the standalone-repo migration out of `daita-agents`.
Not individually documented.
