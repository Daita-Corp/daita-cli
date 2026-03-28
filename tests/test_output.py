"""Tests for OutputFormatter."""

import json
import sys
from io import StringIO

import pytest

from daita_cli.output import OutputFormatter


def capture(fn):
    """Run fn() capturing stdout."""
    old = sys.stdout
    sys.stdout = buf = StringIO()
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


def capture_stderr(fn):
    old = sys.stderr
    sys.stderr = buf = StringIO()
    try:
        fn()
    finally:
        sys.stderr = old
    return buf.getvalue()


def test_json_mode_success():
    f = OutputFormatter(mode="json")
    out = capture(lambda: f.success({"foo": "bar"}))
    parsed = json.loads(out)
    assert parsed["status"] == "ok"
    assert parsed["data"] == {"foo": "bar"}


def test_json_mode_error_goes_to_stderr():
    f = OutputFormatter(mode="json")
    err = capture_stderr(lambda: f.error("AUTH_ERROR", "bad key"))
    parsed = json.loads(err)
    assert parsed["status"] == "error"
    assert parsed["code"] == "AUTH_ERROR"


def test_text_mode_success_message():
    f = OutputFormatter(mode="text")
    out = capture(lambda: f.success(message="All good"))
    assert "All good" in out


def test_list_items_json():
    f = OutputFormatter(mode="json")
    items = [{"id": "1", "name": "agent_a"}]
    out = capture(lambda: f.list_items(items, columns=["id", "name"]))
    parsed = json.loads(out)
    assert parsed["count"] == 1
    assert parsed["items"] == items


def test_list_items_text():
    f = OutputFormatter(mode="text")
    items = [{"id": "1", "name": "agent_a"}]
    out = capture(lambda: f.list_items(items, columns=["id", "name"], title="Agents"))
    assert "agent_a" in out
    assert "Agents" in out


def test_is_json_property():
    assert OutputFormatter(mode="json").is_json is True
    assert OutputFormatter(mode="text").is_json is False


def test_progress_suppressed_in_json():
    f = OutputFormatter(mode="json")
    out = capture(lambda: f.progress("loading..."))
    assert out == ""


def test_progress_shown_in_text():
    f = OutputFormatter(mode="text")
    out = capture(lambda: f.progress("loading..."))
    assert "loading..." in out
