"""
OutputFormatter — json/text/table output for CLI commands.

- json mode: machine-readable, goes to stdout, used by pipes and --output json
- text mode: human-readable, used in TTY without explicit --output
- table mode: like text but aligned columns

Auto-detect: if stdout is not a TTY (pipe/redirect), defaults to json.
Override via --output flag or DAITA_OUTPUT env var.
"""

import json
import os
import sys
from typing import Any


class OutputFormatter:
    def __init__(self, mode: str = None):
        if mode:
            self.mode = mode
        elif os.getenv("DAITA_OUTPUT"):
            self.mode = os.getenv("DAITA_OUTPUT")
        elif not sys.stdout.isatty():
            self.mode = "json"
        else:
            self.mode = "text"

    @property
    def is_json(self) -> bool:
        return self.mode == "json"

    def success(self, data: Any = None, message: str = None) -> None:
        if self.is_json:
            payload: dict = {"status": "ok"}
            if data is not None:
                payload["data"] = data
            print(json.dumps(payload))
        else:
            if message:
                print(message)
            elif data is not None:
                print(json.dumps(data, indent=2, default=str))

    def error(self, code: str, message: str, details: dict = None) -> None:
        if self.is_json:
            payload = {"status": "error", "code": code, "message": message}
            if details:
                payload["details"] = details
            print(json.dumps(payload), file=sys.stderr)
        else:
            print(f"Error: {message}", file=sys.stderr)
            if details:
                for k, v in details.items():
                    print(f"  {k}: {v}", file=sys.stderr)

    def item(self, data: dict, fields: list[str] = None) -> None:
        if self.is_json:
            print(json.dumps(data, default=str))
        else:
            pairs = [(k, data[k]) for k in (fields or data.keys()) if k in data]
            for k, v in pairs:
                print(f"  {k}: {v}")

    def list_items(self, items: list[dict], columns: list[str], title: str = None) -> None:
        if self.is_json:
            print(json.dumps({"items": items, "count": len(items)}, default=str))
            return

        if title:
            print(f"\n{title} ({len(items)})")
        if not items:
            print("  No items found.")
            return

        # Compute column widths
        widths = {col: len(col) for col in columns}
        for item in items:
            for col in columns:
                val = str(item.get(col, ""))
                if len(val) > widths[col]:
                    widths[col] = min(len(val), 40)

        # Header
        header = "  " + "  ".join(col.upper().ljust(widths[col]) for col in columns)
        sep = "  " + "  ".join("-" * widths[col] for col in columns)
        print(header)
        print(sep)

        # Rows
        for item in items:
            row = "  " + "  ".join(
                str(item.get(col, ""))[:widths[col]].ljust(widths[col])
                for col in columns
            )
            print(row)

    def progress(self, message: str) -> None:
        if not self.is_json:
            print(message)
