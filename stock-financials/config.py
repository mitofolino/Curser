import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID", "1KdsG5dtreGC594_1gMtFu2VrMjRaWBF7Rxo3OMbkSic"
)
SHEET_GID = int(os.getenv("SHEET_GID", "238235490"))
TICKER_COLUMN = int(os.getenv("TICKER_COLUMN", "0"))
DATA_START_ROW = int(os.getenv("DATA_START_ROW", "1"))
DRIVE_FOLDER_ID = os.getenv(
    "DRIVE_FOLDER_ID", "1btHnuWAbnEPmJAiMH2lBfcl7k0Q1-0m7"
)
LOCAL_OUTPUT_DIR = Path(os.getenv("LOCAL_OUTPUT_DIR", "./output"))
DOWNLOAD_10K = os.getenv("DOWNLOAD_10K", "true").lower() in ("1", "true", "yes")
SEC_FILINGS_LIMIT = int(os.getenv("SEC_FILINGS_LIMIT", "3"))
SEC_EMAIL = os.getenv("SEC_EMAIL", "your.email@example.com")
DOWNLOAD_QUARTERLY = os.getenv("DOWNLOAD_QUARTERLY", "true").lower() in (
    "1",
    "true",
    "yes",
)
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")
