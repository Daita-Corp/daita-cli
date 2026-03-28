"""
daita push — package the current project and deploy it to the cloud.

Packages: zipfile of user code (agents/, workflows/, daita-project.yaml, requirements.txt)
Upload:   multipart POST to /api/v1/packages/upload
Deploy:   POST to /api/v1/packages/deploy with config metadata

No daita-agents dependency required.
"""

import asyncio
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import click
import httpx
import yaml

from daita_cli import __version__
from daita_cli.output import OutputFormatter
from daita_cli.project_utils import ensure_project_root, load_project_config

_DEFAULT_BASE = "https://api.daita-tech.io"

_EXCLUDE_DIRS = {
    ".daita", "__pycache__", ".git", ".pytest_cache",
    "venv", "env", ".venv", "node_modules", ".mypy_cache",
    "tests", "data",
}
_EXCLUDE_FILES = {".env", ".env.local"}

# Minimal bootstrap handler injected into every deployment package
_BOOTSTRAP = '''\
"""Bootstrap handler for Daita Lambda functions."""
import json

def lambda_handler(event, context):
    try:
        from cloud.lambda_handler import lambda_handler as h
        return h(event, context)
    except ImportError as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
'''


@click.command("push")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.option("--dry-run", is_flag=True, help="Show what would be deployed without deploying")
@click.pass_context
def push_command(ctx, force, dry_run):
    """Deploy current project to the cloud."""
    obj = ctx.obj or {}
    formatter = obj.get("formatter", OutputFormatter())

    try:
        asyncio.run(_push(force, dry_run, formatter, ctx.obj.get("verbose", False)))
    except click.ClickException:
        raise
    except KeyboardInterrupt:
        click.echo("\n  Deployment cancelled.", err=True)
        sys.exit(130)
    except Exception as e:
        formatter.error("ERROR", str(e))
        sys.exit(1)


async def _push(force: bool, dry_run: bool, formatter: OutputFormatter, verbose: bool):
    api_key = os.getenv("DAITA_API_KEY")
    if not api_key:
        raise click.ClickException(
            "DAITA_API_KEY not set.\n"
            "Set it with: export DAITA_API_KEY='your-key'\n"
            "Get your API key at: https://daita-tech.io"
        )

    project_root = ensure_project_root()
    config = load_project_config(project_root)
    if not config:
        raise click.ClickException("No daita-project.yaml found.")
    if not config.get("version"):
        raise click.ClickException("'version' must be set in daita-project.yaml.")

    project_name = config["name"]
    environment = "production"

    formatter.progress(f"  Deploying '{project_name}' to Daita-managed {environment}")

    if dry_run:
        _show_plan(project_root, config, formatter)
        return

    if not force:
        click.confirm(f"  Deploy '{project_name}' to {environment}?", abort=True)

    # Create zip package
    formatter.progress("  Creating deployment package...")
    package_path = _create_package(project_root, config, verbose)

    try:
        base_url = (os.getenv("DAITA_API_ENDPOINT") or _DEFAULT_BASE).rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": f"Daita-CLI/{__version__}",
        }

        # Upload
        formatter.progress("  Uploading package...")
        upload_result = await _upload(package_path, project_name, environment, base_url, headers, verbose)
        upload_id = upload_result["upload_id"]

        if verbose:
            formatter.progress(f"    Upload ID: {upload_id}")

        # Deploy
        formatter.progress("  Deploying...")
        framework_version = _detect_framework_version(project_root)
        deploy_result = await _deploy(
            upload_id, project_name, environment, framework_version, config, base_url, headers, verbose
        )

        formatter.success(
            {"deployment_id": deploy_result.get("deployment_id", ""), "environment": environment},
            message=(
                f"\n  Deployed '{project_name}' to {environment}\n"
                f"  Deployment ID: {deploy_result.get('deployment_id', 'N/A')}\n"
                f"\n  daita status        # Check deployment status\n"
                f"  daita executions list  # View executions"
            ),
        )
    finally:
        if package_path.exists():
            os.unlink(package_path)


def _create_package(project_root: Path, config: dict, verbose: bool) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        package_path = Path(f.name)

    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in project_root.iterdir():
            if item.is_dir() and item.name not in _EXCLUDE_DIRS and not item.name.startswith("."):
                for file_path in item.rglob("*"):
                    if file_path.is_file() and file_path.name not in _EXCLUDE_FILES:
                        arc = f"{item.name}/{file_path.relative_to(item)}"
                        zf.write(file_path, arc)
                if verbose:
                    count = len(list(item.rglob("*.py")))
                    click.echo(f"    Added: {item.name}/ ({count} .py files)")

        for fname in ["daita-project.yaml", "requirements.txt"]:
            p = project_root / fname
            if p.exists():
                zf.write(p, fname)

        zf.writestr("lambda_handler.py", _BOOTSTRAP)

    size_mb = package_path.stat().st_size / 1024 / 1024
    if verbose:
        click.echo(f"    Package size: {size_mb:.1f}MB")

    return package_path


async def _upload(
    package_path: Path,
    project_name: str,
    environment: str,
    base_url: str,
    headers: dict,
    verbose: bool,
) -> dict:
    pkg_bytes = package_path.read_bytes()
    pkg_hash = hashlib.sha256(pkg_bytes).hexdigest()

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{base_url}/api/v1/packages/upload",
            headers={k: v for k, v in headers.items() if k != "Content-Type"},
            files={"package": (f"{project_name}.zip", pkg_bytes, "application/zip")},
            data={"project_name": project_name, "environment": environment},
        )

    if resp.status_code == 200:
        result = resp.json()
        result.setdefault("package_hash", pkg_hash)
        return result
    elif resp.status_code == 401:
        raise click.ClickException("Authentication failed — check your DAITA_API_KEY.")
    elif resp.status_code == 413:
        raise click.ClickException("Package too large (max 250MB). Remove large files.")
    else:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise click.ClickException(f"Upload failed (HTTP {resp.status_code}): {detail}")


async def _deploy(
    upload_id: str,
    project_name: str,
    environment: str,
    framework_version: str,
    config: dict,
    base_url: str,
    headers: dict,
    verbose: bool,
) -> dict:
    agents = [
        {"name": a.get("name"), "type": a.get("type", "standard"), "enabled": a.get("enabled", True)}
        for a in config.get("agents", [])
    ]
    workflows = [
        {"name": w.get("name"), "type": w.get("type", "basic"), "enabled": w.get("enabled", True)}
        for w in config.get("workflows", [])
    ]

    payload = {
        "upload_id": upload_id,
        "project_name": project_name,
        "environment": environment,
        "framework_version": framework_version,
        "version": config["version"],
        "agents_config": agents,
        "workflows_config": workflows,
        "import_analysis": {},
        "layer_requirements": {},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{base_url}/api/v1/packages/deploy",
            headers=headers,
            json=payload,
        )

    if resp.status_code == 200:
        return resp.json()
    elif resp.status_code == 401:
        raise click.ClickException("Authentication failed during deployment.")
    elif resp.status_code == 404:
        raise click.ClickException("Upload expired — try again.")
    else:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise click.ClickException(f"Deployment failed (HTTP {resp.status_code}): {detail}")


def _detect_framework_version(project_root: Path) -> str:
    req = project_root / "requirements.txt"
    if req.exists():
        for line in req.read_text().splitlines():
            line = line.strip()
            if "daita-agents" in line.lower():
                for sep in ("==", ">=", "~="):
                    if sep in line:
                        v = line.split(sep)[1].split("#")[0].strip().split()[0]
                        if v:
                            return v
    try:
        import importlib.metadata
        return importlib.metadata.version("daita-agents")
    except Exception:
        return "0.12.1"


def _show_plan(project_root: Path, config: dict, formatter: OutputFormatter):
    agents = [a.get("name") for a in config.get("agents", [])]
    workflows = [w.get("name") for w in config.get("workflows", [])]
    formatter.success(
        {
            "project": config["name"],
            "version": config.get("version"),
            "agents": agents,
            "workflows": workflows,
        },
        message=(
            f"\n  Dry run — would deploy:\n"
            f"    project:   {config['name']}  v{config.get('version')}\n"
            f"    agents:    {', '.join(agents) or 'none'}\n"
            f"    workflows: {', '.join(workflows) or 'none'}"
        ),
    )
