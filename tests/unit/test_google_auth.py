"""Unit tests for GoogleAuthManager — all Google library calls mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trippy.ingest.google_auth import ALL_SCOPES, GoogleAuthManager, missing_required_scopes


def _manager(tmp_path: Path, credentials: object | None = None) -> GoogleAuthManager:
    return GoogleAuthManager(
        credentials_path=tmp_path / "creds.json",
        token_path=tmp_path / "token.json",
        credentials=credentials,
    )


class TestInjectedCredentials:
    def test_returns_injected_creds_immediately(self, tmp_path: Path) -> None:
        mock_creds = MagicMock()
        mgr = _manager(tmp_path, credentials=mock_creds)
        assert mgr.get_credentials() is mock_creds

    def test_no_disk_access_when_injected(self, tmp_path: Path) -> None:
        mock_creds = MagicMock()
        mgr = _manager(tmp_path, credentials=mock_creds)
        mgr.get_credentials()
        assert not (tmp_path / "token.json").exists()


class TestLoadValidTokenFromDisk:
    def test_returns_valid_creds_without_refresh(self, tmp_path: Path) -> None:
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch("trippy.ingest.google_auth.GoogleAuthManager._load_or_refresh") as mock_load:
            mock_load.return_value = mock_creds
            mgr = _manager(tmp_path)
            result = mgr.get_credentials()

        assert result is mock_creds
        mock_load.assert_called_once()


class TestRefreshExpiredToken:
    def test_calls_refresh_when_expired(self, tmp_path: Path) -> None:
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "rt"

        with (
            patch("trippy.ingest.google_auth.Credentials", create=True),
            patch("trippy.ingest.google_auth.Request", create=True),
        ):
            # Patch via the module's deferred imports
            import trippy.ingest.google_auth as ga_module

            original = ga_module.GoogleAuthManager._load_or_refresh

            def patched_load(self: GoogleAuthManager) -> object:
                from google.auth.transport.requests import Request

                creds = mock_creds
                if not creds.valid and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                self._token_path.parent.mkdir(parents=True, exist_ok=True)
                self._token_path.write_text("{}")
                return creds

            ga_module.GoogleAuthManager._load_or_refresh = patched_load  # type: ignore[method-assign]
            try:
                mgr = _manager(tmp_path)
                result = mgr.get_credentials()
                assert result is mock_creds
                mock_creds.refresh.assert_called_once()
            finally:
                ga_module.GoogleAuthManager._load_or_refresh = original  # type: ignore[method-assign]


class TestMissingCredentialsFile:
    def test_raises_file_not_found_when_no_creds(self, tmp_path: Path) -> None:
        mgr = GoogleAuthManager(
            credentials_path=tmp_path / "nonexistent_creds.json",
            token_path=tmp_path / "token.json",
        )
        with pytest.raises(FileNotFoundError, match="Google credentials not found"):
            mgr.get_credentials()


class TestBuildService:
    def test_build_service_calls_discovery(self, tmp_path: Path) -> None:
        mock_creds = MagicMock()
        mgr = _manager(tmp_path, credentials=mock_creds)

        mock_service = MagicMock()
        with patch("googleapiclient.discovery.build", return_value=mock_service) as mock_build:
            service = mgr.build_service("sheets", "v4")

        mock_build.assert_called_once_with("sheets", "v4", credentials=mock_creds)
        assert service is mock_service

    def test_build_service_gmail(self, tmp_path: Path) -> None:
        mock_creds = MagicMock()
        mgr = _manager(tmp_path, credentials=mock_creds)

        with patch("googleapiclient.discovery.build") as mock_build:
            mgr.build_service("gmail", "v1")

        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)


class TestScopes:
    def test_default_scopes_include_all(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        assert set(mgr._scopes) == set(ALL_SCOPES)

    def test_custom_scopes_respected(self, tmp_path: Path) -> None:
        scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        mgr = GoogleAuthManager(
            credentials_path=tmp_path / "c.json",
            token_path=tmp_path / "t.json",
            scopes=scopes,
        )
        assert list(mgr._scopes) == scopes

    def test_default_scopes_include_write_capable_sheets_and_drive(self) -> None:
        assert "https://www.googleapis.com/auth/gmail.readonly" in ALL_SCOPES
        assert "https://www.googleapis.com/auth/spreadsheets" in ALL_SCOPES
        assert "https://www.googleapis.com/auth/drive" in ALL_SCOPES
        assert "https://www.googleapis.com/auth/spreadsheets.readonly" not in ALL_SCOPES
        assert "https://www.googleapis.com/auth/drive.readonly" not in ALL_SCOPES

    def test_missing_required_scopes_detects_stale_token(self, tmp_path: Path) -> None:
        token = tmp_path / "token.json"
        token.write_text(
            '{"scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}',
            encoding="utf-8",
        )

        missing = missing_required_scopes(token)

        assert "https://www.googleapis.com/auth/spreadsheets" in missing
        assert "https://www.googleapis.com/auth/drive" in missing
