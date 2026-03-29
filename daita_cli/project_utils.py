"""
Shared project utilities — finding project root, loading config, etc.
No daita-agents dependency.
"""

from pathlib import Path
from typing import Optional


def find_project_root(start: Path = None) -> Optional[Path]:
    """Walk upward from start (or cwd) looking for daita-project.yaml."""
    current = start or Path.cwd()
    for p in [current] + list(current.parents):
        if (p / "daita-project.yaml").exists():
            return p
    return None


def ensure_project_root() -> Path:
    root = find_project_root()
    if not root:
        import click
        raise click.ClickException("No daita-project.yaml found. Add one or run 'daita init' to scaffold a new project.")
    return root


def load_project_config(project_root: Path) -> Optional[dict]:
    import yaml
    cfg = project_root / "daita-project.yaml"
    if not cfg.exists():
        return None
    try:
        with open(cfg) as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def list_python_files(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(f.stem for f in directory.glob("*.py") if f.name != "__init__.py")
