from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from googleapiclient.http import MediaFileUpload

import pandas as pd

from google_auth import drive_service, sheets_service

logger = logging.getLogger(__name__)


def upload_file(local_path: Path, folder_id: str, subfolder: str | None = None) -> str:
    """Upload a file to Drive; optionally create/use a subfolder per ticker."""
    service = drive_service()
    parent = folder_id

    if subfolder:
        parent = _ensure_folder_path(service, folder_id, subfolder)

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


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _ensure_folder_path(service, root_id: str, path: str) -> str:
    parent_id = root_id
    for name in path.split("/"):
        name = name.strip()
        if name:
            parent_id = _ensure_folder(service, parent_id, name)
    return parent_id


def _ensure_folder(service, parent_id: str, name: str) -> str:
    safe_name = _escape_query(name)
    query = (
        f"name = '{safe_name}' and '{parent_id}' in parents "
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


def upload_portfolio_summary_sheet(
    df: pd.DataFrame, folder_id: str, *, title: str
) -> str:
    """Create or replace a Google Sheet summary in the Drive root folder."""
    drive = drive_service()
    sheets = sheets_service()

    safe_title = _escape_query(title)
    query = (
        f"name = '{safe_title}' and '{folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    )
    existing = drive.files().list(q=query, fields="files(id, webViewLink)").execute()
    files = existing.get("files", [])

    values = [df.columns.astype(str).tolist()] + df.fillna("").astype(str).values.tolist()

    if files:
        sheet_id = files[0]["id"]
        sheets.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range="A:ZZ"
        ).execute()
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        link = files[0].get("webViewLink")
    else:
        created = (
            drive.files()
            .create(
                body={
                    "name": title,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "parents": [folder_id],
                },
                fields="id, webViewLink",
            )
            .execute()
        )
        sheet_id = created["id"]
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        link = created.get("webViewLink")

    return link or f"https://docs.google.com/spreadsheets/d/{sheet_id}"
