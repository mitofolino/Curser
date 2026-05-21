import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_OUTPUT_DIR = Path("/Users/mitjarebec/Documents/Stocks_Analyses")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
STOCKS_XLSX = Path(
    os.getenv("STOCKS_XLSX", str(OUTPUT_DIR / "Stocks.xlsx"))
)
# Column with ticker symbols in Stocks.xlsx (0 = A, 1 = B, …)
TICKER_COLUMN = int(os.getenv("TICKER_COLUMN", "0"))
# First data row (0 = first row; use 1 if row 0 is a header)
DATA_START_ROW = int(os.getenv("DATA_START_ROW", "1"))
# Sheet name (empty = first sheet)
STOCKS_SHEET = os.getenv("STOCKS_SHEET", "").strip() or None

DOWNLOAD_10K = os.getenv("DOWNLOAD_10K", "true").lower() in ("1", "true", "yes")
SEC_FILINGS_LIMIT = int(os.getenv("SEC_FILINGS_LIMIT", "2"))
STATEMENT_YEARS = int(os.getenv("STATEMENT_YEARS", "2"))
SEC_EMAIL = os.getenv("SEC_EMAIL", "your.email@example.com")
DOWNLOAD_QUARTERLY = os.getenv("DOWNLOAD_QUARTERLY", "true").lower() in (
    "1",
    "true",
    "yes",
)
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
