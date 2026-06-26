"""Minimal database-agent command group for Phase 0."""

from __future__ import annotations

import click

from daita_cli.commands.dev import dev_command


@click.group("db")
def db_group():
    """Database-agent workflows."""


db_group.add_command(dev_command)
