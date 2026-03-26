import click
from daita_cli.command_helpers import api_command


@click.group()
def secrets():
    """Manage cloud secrets."""
    pass


@secrets.command("set")
@click.argument("key")
@click.argument("value")
@api_command
async def set_secret(client, formatter, key, value):
    """Store or update an encrypted secret."""
    data = await client.post("/api/v1/secrets", json={"key": key, "value": value})
    formatter.success(data, message=f"Secret '{key}' stored.")


@secrets.command("list")
@api_command
async def list_secrets(client, formatter):
    """List stored secret key names (values are never shown)."""
    data = await client.get("/api/v1/secrets")
    items = data if isinstance(data, list) else data.get("keys", data.get("secrets", data.get("items", [])))
    # Normalise to dicts if items are plain strings
    if items and isinstance(items[0], str):
        items = [{"key": k} for k in items]
    formatter.list_items(items, columns=["key"], title="Secrets")


@secrets.command("remove")
@click.argument("key")
@api_command
async def remove_secret(client, formatter, key):
    """Delete a stored secret."""
    data = await client.delete(f"/api/v1/secrets/{key}")
    formatter.success(data, message=f"Secret '{key}' removed.")


@secrets.command("import")
@click.argument("env_file", default=".env")
@api_command
async def import_secrets(client, formatter, env_file):
    """Import secrets from a .env file into secure cloud storage."""
    import re
    from pathlib import Path

    path = Path(env_file)
    if not path.exists():
        raise click.ClickException(f"File not found: {env_file}")

    imported = 0
    skipped = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9_]*)=(.*)$', line)
        if not m:
            skipped += 1
            continue
        k, v = m.group(1), m.group(2).strip('"').strip("'")
        if not v:
            skipped += 1
            continue
        await client.post("/api/v1/secrets", json={"key": k, "value": v})
        imported += 1

    formatter.success(
        {"imported": imported, "skipped": skipped},
        message=f"Imported {imported} secrets from {env_file} ({skipped} skipped).",
    )
