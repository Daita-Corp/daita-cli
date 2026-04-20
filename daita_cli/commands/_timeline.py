"""
ASCII timeline renderer for trace spans.

Pure, deterministic, no I/O. Used by `daita traces spans` (TTY mode) and
exposed via structured JSON output (so LLM callers get the same data
without parsing ANSI).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Unicode block chars render best on modern terminals; ASCII fallback for
# anything else (CI logs, old SSH clients, locale-limited envs).
_FILL_UNICODE = "█"
_EMPTY_UNICODE = "░"
_FILL_ASCII = "="
_EMPTY_ASCII = "-"

# A span is "slow" if it eats >30% of the total trace duration. Tunable.
_SLOW_RATIO = 0.30


@dataclass
class SpanNode:
    span_id: str
    name: str
    start_ms: float
    duration_ms: float
    status: str = ""
    attributes: dict = field(default_factory=dict)
    children: list["SpanNode"] = field(default_factory=list)
    depth: int = 0
    slow: bool = False


def _get(span: dict, *keys, default=None):
    """First present key wins. Lets us tolerate naming variance across API responses."""
    for k in keys:
        if k in span and span[k] is not None:
            return span[k]
    return default


def _start_ms(span: dict) -> float:
    """Extract a start-offset millisecond value. Tolerates epoch-ms or ISO timestamps."""
    raw = _get(span, "start_ms", "start_time_ms", "started_at_ms", "start_offset_ms")
    if raw is not None:
        return float(raw)
    # Fall back to ISO timestamp if the backend sends those
    started = _get(span, "startTime", "started_at", "start_time")
    if isinstance(started, str):
        from datetime import datetime
        try:
            return datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            return 0.0
    return 0.0


def build_tree(spans: list[dict]) -> list[SpanNode]:
    """Build a forest of SpanNodes from a flat span list.

    Normalizes start times to offsets from the earliest span so the timeline
    is always relative to the trace start.
    """
    if not spans:
        return []

    nodes: dict[str, SpanNode] = {}
    for s in spans:
        nid = _get(s, "spanId", "span_id", "id", default="")
        if not nid:
            continue
        nodes[nid] = SpanNode(
            span_id=nid,
            name=_get(s, "operationName", "name", "operation_name", default="(unnamed)"),
            start_ms=_start_ms(s),
            duration_ms=float(_get(s, "duration_ms", "duration", default=0) or 0),
            status=_get(s, "status", default=""),
            attributes=_get(s, "attributes", "metadata", default={}) or {},
        )

    # Normalize to relative offsets
    earliest = min((n.start_ms for n in nodes.values()), default=0.0)
    for n in nodes.values():
        n.start_ms = max(0.0, n.start_ms - earliest)

    # Link children to parents
    roots: list[SpanNode] = []
    for s in spans:
        nid = _get(s, "spanId", "span_id", "id", default="")
        if not nid or nid not in nodes:
            continue
        parent_id = _get(s, "parentSpanId", "parent_span_id", "parent_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id].children.append(nodes[nid])
        else:
            roots.append(nodes[nid])

    # Assign depth and sort children by start time
    def _assign(node: SpanNode, d: int):
        node.depth = d
        node.children.sort(key=lambda c: c.start_ms)
        for c in node.children:
            _assign(c, d + 1)

    roots.sort(key=lambda n: n.start_ms)
    for r in roots:
        _assign(r, 0)
    return roots


def flag_slow(roots: list[SpanNode], total_ms: float, ratio: float = _SLOW_RATIO) -> None:
    """Mark spans whose duration exceeds `ratio` of total trace duration."""
    if total_ms <= 0:
        return
    threshold = total_ms * ratio

    def _walk(n: SpanNode):
        if n.duration_ms > threshold:
            n.slow = True
        for c in n.children:
            _walk(c)

    for r in roots:
        _walk(r)


def trace_duration(roots: list[SpanNode]) -> float:
    """Total duration = max(end_ms) across roots."""
    if not roots:
        return 0.0
    return max(r.start_ms + r.duration_ms for r in roots)


def _fmt_duration(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    m = int(ms // 60_000)
    s = (ms % 60_000) / 1000
    return f"{m}m {s:.1f}s"


def _render_bar(
    start_ms: float,
    duration_ms: float,
    total_ms: float,
    width: int,
    ascii_only: bool,
) -> str:
    if total_ms <= 0 or width <= 0:
        return ""
    fill = _FILL_ASCII if ascii_only else _FILL_UNICODE
    empty = _EMPTY_ASCII if ascii_only else _EMPTY_UNICODE

    start_cell = int((start_ms / total_ms) * width)
    span_cells = max(1, int((duration_ms / total_ms) * width))
    start_cell = min(start_cell, width - 1)
    span_cells = min(span_cells, width - start_cell)

    return (
        empty * start_cell
        + fill * span_cells
        + empty * (width - start_cell - span_cells)
    )


def render_timeline(
    spans: list[dict],
    *,
    width: int = 80,
    ascii_only: bool = False,
    min_duration_ms: float = 0,
) -> str:
    """Render an ASCII timeline from a flat span list.

    Auto-builds the tree, flags slow spans, and emits a multi-line string
    ready to print. Spans below `min_duration_ms` are suppressed.
    """
    roots = build_tree(spans)
    if not roots:
        return "No spans to display."

    total_ms = trace_duration(roots)
    flag_slow(roots, total_ms)

    # Determine name column width (capped to keep bars usable)
    name_col = 0

    def _probe_width(node: SpanNode):
        nonlocal name_col
        label = "  " * node.depth + ("└─ " if node.depth else "") + node.name
        name_col = max(name_col, len(label))
        for c in node.children:
            _probe_width(c)

    for r in roots:
        _probe_width(r)
    name_col = min(name_col, max(20, width // 3))

    bar_width = max(10, width - name_col - 20)  # leave room for timing + tags
    lines: list[str] = []

    # Header
    lines.append(f"Total: {_fmt_duration(total_ms)}   |   bar = {bar_width} cells")
    lines.append("─" * min(width, 80))

    def _emit(node: SpanNode, is_last: bool = False, prefix: str = ""):
        if node.duration_ms < min_duration_ms:
            return
        connector = "└─ " if node.depth and is_last else ("├─ " if node.depth else "")
        label = (prefix + connector + node.name)[:name_col].ljust(name_col)
        bar = _render_bar(node.start_ms, node.duration_ms, total_ms, bar_width, ascii_only)
        tag = " ⚠ slow" if node.slow else ""
        lines.append(f"{label}  [{bar}]  {_fmt_duration(node.duration_ms)}{tag}")

        # Prefix for grandchildren
        child_prefix = prefix + ("    " if is_last else "│   ") if node.depth else ""
        for i, c in enumerate(node.children):
            _emit(c, is_last=(i == len(node.children) - 1), prefix=child_prefix)

    for i, r in enumerate(roots):
        _emit(r, is_last=(i == len(roots) - 1))

    fill = _FILL_ASCII if ascii_only else _FILL_UNICODE
    empty = _EMPTY_ASCII if ascii_only else _EMPTY_UNICODE
    lines.append("")
    lines.append(f"Legend: {fill} active   {empty} waiting   ⚠ exceeds {int(_SLOW_RATIO * 100)}% of total")

    return "\n".join(lines)


def compute_bottlenecks(spans: list[dict]) -> list[dict]:
    """Return a structured list of slow spans (for --json / MCP callers)."""
    roots = build_tree(spans)
    total = trace_duration(roots)
    flag_slow(roots, total)

    out: list[dict] = []

    def _walk(n: SpanNode):
        if n.slow:
            out.append({
                "span_id": n.span_id,
                "name": n.name,
                "duration_ms": n.duration_ms,
                "share": round(n.duration_ms / total, 3) if total > 0 else 0,
            })
        for c in n.children:
            _walk(c)

    for r in roots:
        _walk(r)
    return out
