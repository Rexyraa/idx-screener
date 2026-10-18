from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def get_config_path(name: str) -> Path:
    """Return a path to a project-level configuration file."""
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "configs" / name


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data
