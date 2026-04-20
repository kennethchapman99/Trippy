"""trippy-gmail-reconciler skill runner."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GmailReconcilerRunner:
    skill_name = "trippy-gmail-reconciler"

    def __init__(
        self,
        trips_dir: Path | None = None,
        auth_manager: Any | None = None,
        anthropic_client: Any | None = None,
    ) -> None:
        self._trips_dir = trips_dir
        self._auth_manager = auth_manager
        self._anthropic_client = anthropic_client

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from trippy import config
        from trippy.db import make_session_factory
        from trippy.ingest.gmail_watcher import GmailWatcher
        from trippy.ingest.google_auth import GoogleAuthManager
        from trippy.ingest.linker import ingest_email
        from trippy.ingest.parser import ConfirmationParser

        max_emails: int = inputs.get("max_emails", 50)

        auth = self._auth_manager or GoogleAuthManager()
        watcher = GmailWatcher(auth_manager=auth)
        watcher.authenticate()

        emails = watcher.fetch_new_messages(max_results=max_emails)
        logger.info("GmailReconciler: fetched %d candidate emails", len(emails))

        parser = ConfirmationParser(anthropic_client=self._anthropic_client)
        factory = make_session_factory()

        linked_count = 0
        unlinked_count = 0
        failed_count = 0
        updates: list[dict[str, Any]] = []
        unlinked: list[dict[str, Any]] = []

        vault_path = config.VAULT_PATH

        for email_content in emails:
            eml_path = watcher.save_to_vault(email_content, vault_path)
            atts = [(a.filename, a.content_type, a.data) for a in email_content.attachments]
            parse_result = parser.parse(
                body_text=email_content.body_text,
                body_html=email_content.body_html,
                attachments=atts,
                eml_path=eml_path,
            )

            if not parse_result.ok or parse_result.confirmation is None:
                failed_count += 1
                continue

            conf = parse_result.confirmation
            with factory() as session:
                link = ingest_email(conf, session, raw_email_path=str(eml_path))

            if link.linked:
                linked_count += 1
                updates.append(
                    {
                        "trip_id": link.trip_id,
                        "confirmation_code": conf.confirmation_code,
                        "vendor": conf.vendor,
                        "method": link.method,
                    }
                )
            else:
                unlinked_count += 1
                unlinked.append(
                    {
                        "vendor": conf.vendor,
                        "code": conf.confirmation_code,
                        "type": conf.confirmation_type,
                        "reason": "No matching trip found",
                    }
                )

        return {
            "emails_scanned": len(emails),
            "confirmations_parsed": linked_count + unlinked_count,
            "confirmations_linked": linked_count,
            "confirmations_unlinked": unlinked_count,
            "parse_failures": failed_count,
            "updates": updates,
            "unlinked": unlinked,
        }
