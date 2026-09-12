"""Thin wrapper around the Drive API: reading Doc text and posting comments."""
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


class DriveClient:
    def __init__(self, credentials):
        self.service = build("drive", "v3", credentials=credentials)

    def get_revision_id(self, file_id: str) -> str:
        meta = self.service.files().get(fileId=file_id, fields="headRevisionId").execute()
        return meta.get("headRevisionId", "")

    def export_text(self, file_id: str) -> str:
        """Export a Google Doc as plain text."""
        request = self.service.files().export_media(fileId=file_id, mimeType="text/plain")
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")

    def post_comment(self, file_id: str, content: str):
        self.service.comments().create(
            fileId=file_id, body={"content": content}, fields="id"
        ).execute()
