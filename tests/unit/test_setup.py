"""Tests for first-run setup diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trippy.ingest.google_auth import ALL_SCOPES
from trippy.services.setup import CheckStatus, SetupDoctor


def _patch_config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from trippy import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "state.db")
    monkeypatch.setattr(config, "MEMORY_PATH", tmp_path / "memory.json")
    monkeypatch.setattr(config, "TRIPS_PATH", tmp_path / "trips")
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path / "vault")
    monkeypatch.setattr(config, "EXPORT_PATH", tmp_path / "export")
    monkeypatch.setattr(config, "LEARNING_PATH", tmp_path / "learning")
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", tmp_path / "gmail_credentials.json")
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", tmp_path / "gmail_token.json")
    monkeypatch.setattr(config, "GOOGLE_TOKEN_PATH", tmp_path / "google_token.json")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")


def test_doctor_reports_missing_google_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config_paths(tmp_path, monkeypatch)
    (tmp_path / "gmail_credentials.json").write_text("{}", encoding="utf-8")

    report = SetupDoctor(project_root=tmp_path).run()

    token_check = report.check("google_token")
    assert token_check is not None
    assert token_check.status == CheckStatus.FAIL


def test_doctor_reports_stale_google_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config_paths(tmp_path, monkeypatch)
    (tmp_path / "gmail_credentials.json").write_text("{}", encoding="utf-8")
    (tmp_path / "google_token.json").write_text(
        json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}),
        encoding="utf-8",
    )

    report = SetupDoctor(project_root=tmp_path).run()

    scopes_check = report.check("google_scopes")
    assert scopes_check is not None
    assert scopes_check.status == CheckStatus.FAIL
    assert "spreadsheets" in (scopes_check.detail or "")


def test_doctor_accepts_required_google_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config_paths(tmp_path, monkeypatch)
    (tmp_path / "gmail_credentials.json").write_text("{}", encoding="utf-8")
    (tmp_path / "google_token.json").write_text(
        json.dumps({"scopes": list(ALL_SCOPES)}),
        encoding="utf-8",
    )

    report = SetupDoctor(project_root=tmp_path).run()

    scopes_check = report.check("google_scopes")
    assert scopes_check is not None
    assert scopes_check.status == CheckStatus.PASS
