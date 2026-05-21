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
STATEMENT_YEARS = int(os.getenv("STATEMENT_YEARS", "5"))
SEC_FILINGS_LIMIT = int(os.getenv("SEC_FILINGS_LIMIT", str(STATEMENT_YEARS)))
SEC_EMAIL = os.getenv("SEC_EMAIL", "your.email@example.com")
DOWNLOAD_QUARTERLY = os.getenv("DOWNLOAD_QUARTERLY", "true").lower() in (
    "1",
    "true",
    "yes",
)
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()

PORTFOLIO_NUMBERS_PATH = Path(
    os.getenv(
        "PORTFOLIO_NUMBERS_PATH",
        str(OUTPUT_DIR / "portfolio_summary.numbers"),
    )
)
PORTFOLIO_SHEET_NAME = os.getenv("PORTFOLIO_SHEET_NAME", "portfolio")
# Portfolio summary output: numbers | xlsx | both
PORTFOLIO_OUTPUT = os.getenv("PORTFOLIO_OUTPUT", "numbers").strip().lower()

# eToro Public API: x-api-key (public) + x-user-key (private / user key from eToro settings)
ETORO_API_URL = os.getenv("ETORO_API_URL", "https://public-api.etoro.com/api/v1").strip()
ETORO_API_PUBLIC_KEY = os.getenv("ETORO_API_PUBLIC_KEY", "").strip()
ETORO_API_PRIVATE_KEY = os.getenv("ETORO_API_PRIVATE_KEY", "").strip()
ETORO_USER_KEY = ETORO_API_PRIVATE_KEY or os.getenv("ETORO_API_USER_KEY", "").strip()
ETORO_CSV_PATH = (
    Path(os.getenv("ETORO_CSV_PATH", "")).expanduser()
    if os.getenv("ETORO_CSV_PATH")
    else None
)
_etoro_flag = os.getenv("ETORO_ENABLED", "").lower()
if _etoro_flag in ("1", "true", "yes"):
    ETORO_ENABLED = True
elif _etoro_flag in ("0", "false", "no"):
    ETORO_ENABLED = False
else:
    ETORO_ENABLED = bool(ETORO_API_PUBLIC_KEY and ETORO_USER_KEY)

# Numbers portfolio table: 1-based row where data starts (2 = keep row 1 as headers)
PORTFOLIO_DATA_START_ROW = int(os.getenv("PORTFOLIO_DATA_START_ROW", "2"))

# IBKR Client Portal — gateway must be running; or use CSV export
IBKR_ENABLED = os.getenv("IBKR_ENABLED", "false").lower() in ("1", "true", "yes")
IBKR_CPAPI_URL = os.getenv("IBKR_CPAPI_URL", "https://localhost:5000/v1/api").strip()
IBKR_ACCOUNT_ID = os.getenv("IBKR_ACCOUNT_ID", "").strip()
IBKR_VERIFY_SSL = os.getenv("IBKR_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
IBKR_CSV_PATH = Path(os.getenv("IBKR_CSV_PATH", "")).expanduser() if os.getenv("IBKR_CSV_PATH") else None
