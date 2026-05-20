from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from config import DRIVE_FOLDER_ID
from google_auth import drive_service

logger = logging.getLogger(__name__)


def upload_file(local_path: Path, folder_id: str, subfolder: str | None = None) -> str:
    """Upload a file to Drive; optionally create/use a subfolder per ticker."""
    service = drive_service()
    parent = folder_id

    if subfolder:
        parent = _ensure_folder(service, folder_id, subfolder)

    mime, _ = mimetypes.guess_type(str(local_path))
    if mime is None:
        mime = "application/octet-stream"

    metadata = {"name": local_path.name, "parents": [parent]}
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)
    created = (
        service.files()
        .create(body=metadata, media_body=media, fields="id, webViewLink")
        .execute()
    )
    logger.info("Uploaded %s -> %s", local_path.name, created.get("webViewLink"))
    return created["id"]


def _ensure_folder(service, parent_id: str, name: str) -> str:
    query = (
        f"name = '{name}' and '{parent_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = service.files().list(q=query, fields="files(id)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=body, fields="id").execute()
    return folder["id"]
