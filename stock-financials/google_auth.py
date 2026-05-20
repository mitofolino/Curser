from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import CREDENTIALS_FILE, SCOPES, TOKEN_FILE


def get_credentials() -> Credentials:
    creds: Credentials | None = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_FILE}. See README.md for Google Cloud setup."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            print(
                "\n>>> Sign in with the Google account that owns the sheet and Drive folder.\n"
                ">>> If no browser opens, copy the URL printed below into your browser.\n",
                flush=True,
            )
            creds = flow.run_local_server(port=0, open_browser=True)
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def sheets_service():
    return build("sheets", "v4", credentials=get_credentials())


def drive_service():
    return build("drive", "v3", credentials=get_credentials())
