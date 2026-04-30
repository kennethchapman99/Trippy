"""Regression tests for active package entrypoints."""

import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cli_script_points_to_active_trippy_package() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["trippy"] == "trippy.cli:app"
    cli = importlib.import_module("trippy.cli")
    assert cli.app.info.name == "trippy"


def test_active_package_does_not_reference_legacy_package() -> None:
    legacy_name = "hermes" + "_trip"
    matches = [
        path
        for path in (ROOT / "trippy").rglob("*.py")
        if legacy_name in path.read_text()
    ]

    assert matches == []
