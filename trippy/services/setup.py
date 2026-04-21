"""First-run setup diagnostics and Google OAuth validation."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from trippy import config
from trippy.ingest.google_auth import ALL_SCOPES, GoogleAuthManager, missing_required_scopes


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


class SetupCheck(BaseModel):
    name: str
    status: CheckStatus
    summary: str
    detail: str | None = None


class SetupReport(BaseModel):
    ok: bool
    checks: list[SetupCheck]
    next_actions: list[str] = Field(default_factory=list)

    def check(self, name: str) -> SetupCheck | None:
        for item in self.checks:
            if item.name == name:
                return item
        return None


class SetupDoctor:
    """Deterministic readiness checks for running Trippy locally and live."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or Path.cwd()

    def run(self, *, create_paths: bool = True) -> SetupReport:
        checks = [
            self._check_env_file(),
            *self._check_storage_paths(create_paths=create_paths),
            self._check_database(),
            self._check_anthropic_key(),
            self._check_google_credentials(),
            self._check_google_token(),
            self._check_google_scopes(),
            self._check_sheet_template(),
            self._check_mcp_config(),
        ]
        next_actions = self._next_actions(checks)
        ok = not any(check.status == CheckStatus.FAIL for check in checks)
        return SetupReport(ok=ok, checks=checks, next_actions=next_actions)

    def google_ready(self) -> bool:
        report = self.run()
        required = {"google_credentials", "google_token", "google_scopes"}
        return all(
            check.name not in required or check.status == CheckStatus.PASS
            for check in report.checks
        )

    def _check_env_file(self) -> SetupCheck:
        env_path = self._root / ".env"
        if env_path.exists():
            return SetupCheck(name="env_file", status=CheckStatus.PASS, summary=".env file found")
        return SetupCheck(
            name="env_file",
            status=CheckStatus.WARN,
            summary=".env file not found",
            detail="Copy .env.example to .env when you are ready to use live credentials.",
        )

    def _check_storage_paths(self, *, create_paths: bool) -> list[SetupCheck]:
        checks: list[SetupCheck] = []
        paths = {
            "db_parent": config.DB_PATH.parent,
            "trips_dir": config.TRIPS_PATH,
            "vault_dir": config.VAULT_PATH,
            "export_dir": config.EXPORT_PATH,
            "learning_dir": config.LEARNING_PATH,
        }
        for name, path in paths.items():
            try:
                if create_paths:
                    path.mkdir(parents=True, exist_ok=True)
                    probe = path / ".trippy-write-check"
                    probe.write_text("ok", encoding="utf-8")
                    probe.unlink(missing_ok=True)
                elif not path.exists():
                    checks.append(
                        SetupCheck(
                            name=name,
                            status=CheckStatus.WARN,
                            summary=f"Path does not exist yet: {path}",
                        )
                    )
                    continue
                checks.append(
                    SetupCheck(
                        name=name,
                        status=CheckStatus.PASS,
                        summary=f"Writable: {path}",
                    )
                )
            except Exception as exc:
                checks.append(
                    SetupCheck(
                        name=name,
                        status=CheckStatus.FAIL,
                        summary=f"Not writable: {path}",
                        detail=str(exc),
                    )
                )
        return checks

    def _check_database(self) -> SetupCheck:
        if not config.DB_PATH.exists():
            return SetupCheck(
                name="database",
                status=CheckStatus.WARN,
                summary="Database not initialized",
                detail="Run: trippy db-init",
            )
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "select name from sqlite_master where type = 'table'"
                    ).fetchall()
                }
                if "alembic_version" not in tables:
                    return SetupCheck(
                        name="database",
                        status=CheckStatus.WARN,
                        summary="Database exists but Alembic version table is missing",
                        detail="Run: trippy db-init",
                    )
            return SetupCheck(
                name="database",
                status=CheckStatus.PASS,
                summary=f"Database initialized: {config.DB_PATH}",
            )
        except Exception as exc:
            return SetupCheck(
                name="database",
                status=CheckStatus.FAIL,
                summary=f"Database cannot be inspected: {config.DB_PATH}",
                detail=str(exc),
            )

    def _check_anthropic_key(self) -> SetupCheck:
        key = config.ANTHROPIC_API_KEY.strip()
        if key and not key.startswith("sk-ant-..."):
            return SetupCheck(
                name="anthropic_key", status=CheckStatus.PASS, summary="Anthropic key set"
            )
        return SetupCheck(
            name="anthropic_key",
            status=CheckStatus.FAIL,
            summary="ANTHROPIC_API_KEY is missing",
            detail="Set ANTHROPIC_API_KEY in .env before running the interactive agent or parser.",
        )

    def _check_google_credentials(self) -> SetupCheck:
        if config.GMAIL_CREDENTIALS_PATH.exists():
            return SetupCheck(
                name="google_credentials",
                status=CheckStatus.PASS,
                summary=f"OAuth client secrets found: {config.GMAIL_CREDENTIALS_PATH}",
            )
        return SetupCheck(
            name="google_credentials",
            status=CheckStatus.FAIL,
            summary="Google OAuth client secrets missing",
            detail=f"Save a Desktop OAuth client JSON at {config.GMAIL_CREDENTIALS_PATH}.",
        )

    def _token_path(self) -> Path:
        if config.GOOGLE_TOKEN_PATH.exists():
            return config.GOOGLE_TOKEN_PATH
        return config.GMAIL_TOKEN_PATH

    def _check_google_token(self) -> SetupCheck:
        token_path = self._token_path()
        if token_path.exists():
            return SetupCheck(
                name="google_token",
                status=CheckStatus.PASS,
                summary=f"Google OAuth token found: {token_path}",
            )
        return SetupCheck(
            name="google_token",
            status=CheckStatus.FAIL,
            summary="Google OAuth token missing",
            detail="Run: trippy auth-google",
        )

    def _check_google_scopes(self) -> SetupCheck:
        token_path = self._token_path()
        if not token_path.exists():
            return SetupCheck(
                name="google_scopes",
                status=CheckStatus.SKIP,
                summary="Google OAuth scopes not checked because token is missing",
            )
        try:
            missing = missing_required_scopes(token_path, ALL_SCOPES)
        except Exception as exc:
            return SetupCheck(
                name="google_scopes",
                status=CheckStatus.FAIL,
                summary="Google OAuth token cannot be parsed",
                detail=str(exc),
            )
        if missing:
            return SetupCheck(
                name="google_scopes",
                status=CheckStatus.FAIL,
                summary="Google OAuth token is missing required scopes",
                detail="Run: trippy auth-google --force\nMissing: " + ", ".join(sorted(missing)),
            )
        return SetupCheck(
            name="google_scopes",
            status=CheckStatus.PASS,
            summary="Google OAuth token includes Gmail read, Sheets write, and Drive write scopes",
        )

    def _check_sheet_template(self) -> SetupCheck:
        if config.SHEET_TEMPLATE_ID.strip():
            return SetupCheck(
                name="sheet_template",
                status=CheckStatus.PASS,
                summary="TRIPPY_SHEET_TEMPLATE_ID is configured",
            )
        return SetupCheck(
            name="sheet_template",
            status=CheckStatus.WARN,
            summary="TRIPPY_SHEET_TEMPLATE_ID is not set",
            detail="Trip sheet creation will create a blank Trippy sheet instead of copying a template.",
        )

    def _check_mcp_config(self) -> SetupCheck:
        cfg_path = self._root / "mcp_config.json"
        spec = importlib.util.find_spec("trippy.mcp.server")
        if not cfg_path.exists():
            return SetupCheck(
                name="mcp_config",
                status=CheckStatus.WARN,
                summary="mcp_config.json not found",
            )
        if spec is None:
            return SetupCheck(
                name="mcp_config",
                status=CheckStatus.FAIL,
                summary="trippy.mcp.server is not importable",
            )
        try:
            json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return SetupCheck(
                name="mcp_config",
                status=CheckStatus.FAIL,
                summary="mcp_config.json is not valid JSON",
                detail=str(exc),
            )
        return SetupCheck(
            name="mcp_config",
            status=CheckStatus.PASS,
            summary="MCP config found and server module is importable",
        )

    def _next_actions(self, checks: list[SetupCheck]) -> list[str]:
        by_name = {check.name: check for check in checks}
        actions: list[str] = []
        if (
            by_name.get(
                "anthropic_key", SetupCheck(name="", status=CheckStatus.PASS, summary="")
            ).status
            == CheckStatus.FAIL
        ):
            actions.append("Set ANTHROPIC_API_KEY in .env.")
        if (
            by_name.get(
                "google_credentials", SetupCheck(name="", status=CheckStatus.PASS, summary="")
            ).status
            == CheckStatus.FAIL
        ):
            actions.append(f"Save Google OAuth client secrets to {config.GMAIL_CREDENTIALS_PATH}.")
        if (
            by_name.get(
                "google_token", SetupCheck(name="", status=CheckStatus.PASS, summary="")
            ).status
            == CheckStatus.FAIL
        ):
            actions.append("Run: trippy auth-google")
        if (
            by_name.get(
                "google_scopes", SetupCheck(name="", status=CheckStatus.PASS, summary="")
            ).status
            == CheckStatus.FAIL
        ):
            actions.append("Run: trippy auth-google --force")
        if (
            by_name.get("database", SetupCheck(name="", status=CheckStatus.PASS, summary="")).status
            == CheckStatus.WARN
        ):
            actions.append("Run: trippy db-init")
        return actions


class AuthGoogleResult(BaseModel):
    ok: bool
    checks: list[SetupCheck]


class GoogleAuthValidator:
    """Runs OAuth and validates live Gmail, Sheets, and Drive capabilities."""

    def __init__(self, auth_manager: GoogleAuthManager | None = None) -> None:
        self._auth_manager = auth_manager

    def run(self, *, force: bool = False) -> AuthGoogleResult:
        checks: list[SetupCheck] = []
        if force:
            config.GOOGLE_TOKEN_PATH.unlink(missing_ok=True)
            config.GMAIL_TOKEN_PATH.unlink(missing_ok=True)

        auth = self._auth_manager or GoogleAuthManager(token_path=config.GOOGLE_TOKEN_PATH)
        try:
            auth.get_credentials()
            checks.append(
                SetupCheck(
                    name="oauth",
                    status=CheckStatus.PASS,
                    summary=f"OAuth token ready: {config.GOOGLE_TOKEN_PATH}",
                )
            )
        except Exception as exc:
            checks.append(
                SetupCheck(
                    name="oauth",
                    status=CheckStatus.FAIL,
                    summary="OAuth flow failed",
                    detail=str(exc),
                )
            )
            return AuthGoogleResult(ok=False, checks=checks)

        checks.append(self._validate_gmail(auth))
        temp_sheet_id = ""
        sheet_check, temp_sheet_id = self._validate_sheets(auth)
        checks.append(sheet_check)
        checks.append(self._validate_drive(auth, temp_sheet_id))
        if config.SHEET_TEMPLATE_ID:
            checks.append(self._validate_template(auth))

        ok = not any(check.status == CheckStatus.FAIL for check in checks)
        return AuthGoogleResult(ok=ok, checks=checks)

    def _validate_gmail(self, auth: GoogleAuthManager) -> SetupCheck:
        try:
            service = auth.build_service("gmail", "v1")
            service.users().labels().list(userId="me").execute()
            return SetupCheck(
                name="gmail", status=CheckStatus.PASS, summary="Gmail readonly access works"
            )
        except Exception as exc:
            return SetupCheck(
                name="gmail",
                status=CheckStatus.FAIL,
                summary="Gmail readonly validation failed",
                detail=str(exc),
            )

    def _validate_sheets(self, auth: GoogleAuthManager) -> tuple[SetupCheck, str]:
        title = f"Trippy Auth Validation {datetime.utcnow().isoformat(timespec='seconds')}"
        try:
            service = auth.build_service("sheets", "v4")
            resp = service.spreadsheets().create(body={"properties": {"title": title}}).execute()
            sheet_id = str(resp["spreadsheetId"])
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range="Sheet1!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [["Trippy auth validation"]]},
            ).execute()
            return (
                SetupCheck(
                    name="sheets",
                    status=CheckStatus.PASS,
                    summary="Sheets create/write access works",
                ),
                sheet_id,
            )
        except Exception as exc:
            return (
                SetupCheck(
                    name="sheets",
                    status=CheckStatus.FAIL,
                    summary="Sheets create/write validation failed",
                    detail=str(exc),
                ),
                "",
            )

    def _validate_drive(self, auth: GoogleAuthManager, temp_sheet_id: str) -> SetupCheck:
        try:
            service = auth.build_service("drive", "v3")
            service.files().list(pageSize=1, fields="files(id,name)").execute()
            if temp_sheet_id:
                service.files().delete(fileId=temp_sheet_id).execute()
            return SetupCheck(name="drive", status=CheckStatus.PASS, summary="Drive access works")
        except Exception as exc:
            return SetupCheck(
                name="drive",
                status=CheckStatus.FAIL,
                summary="Drive validation failed",
                detail=str(exc),
            )

    def _validate_template(self, auth: GoogleAuthManager) -> SetupCheck:
        try:
            service = auth.build_service("drive", "v3")
            service.files().get(fileId=config.SHEET_TEMPLATE_ID, fields="id,name").execute()
            return SetupCheck(
                name="sheet_template_access",
                status=CheckStatus.PASS,
                summary="Template sheet is accessible",
            )
        except Exception as exc:
            return SetupCheck(
                name="sheet_template_access",
                status=CheckStatus.FAIL,
                summary="Template sheet cannot be accessed",
                detail=str(exc),
            )
