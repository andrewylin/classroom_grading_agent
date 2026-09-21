"""Thin, read-only wrapper around the Drive API: reading Doc text only.

No write methods here on purpose - this agent never touches student files.
"""
import io
import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from retry_utils import retry_on_transient_error

log = logging.getLogger("drive_client")


class DriveClient:
    def __init__(self, credentials):
        self.service = build("drive", "v3", credentials=credentials)

    def _retry(self, action, description: str, max_retries: int = 4):
        return retry_on_transient_error(action, description, max_retries=max_retries)

    def get_revision_id(self, file_id: str) -> str:
        meta = self._retry(
            lambda: self.service.files().get(fileId=file_id, fields="headRevisionId").execute(),
            f"reading revision metadata for {file_id}",
        )
        return meta.get("headRevisionId", "")

    def export_text(self, file_id: str) -> str:
        """Export a Google Doc as plain text."""
        def do_export():
            request = self.service.files().export_media(fileId=file_id, mimeType="text/plain")
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue().decode("utf-8", errors="replace")

        return self._retry(do_export, f"exporting document {file_id}")
