# Stock financials downloader

Reads ticker symbols from your [Google Sheet](https://docs.google.com/spreadsheets/d/1KdsG5dtreGC594_1gMtFu2VrMjRaWBF7Rxo3OMbkSic/edit?gid=238235490) and downloads financial data for long-term investment analysis into your [Google Drive folder](https://drive.google.com/drive/folders/1btHnuWAbnEPmJAiMH2lBfcl7k0Q1-0m7).

## What gets downloaded (per ticker)

| Output | Source | Use for analysis |
|--------|--------|------------------|
| `{TICKER}_{Company}_financials.xlsx` | Yahoo Finance | Annual **and quarterly** income, balance sheet, cash flow, plus overview metrics |
| `SEC_10-K/` (optional) | SEC EDGAR | Last N annual reports (US-listed companies only) |

### Non-US / global companies

| Approach | Best for | Notes |
|----------|----------|--------|
| **Yahoo Finance** (default) | Most tickers with exchange suffix | Use `IFX.DE`, `3750.HK`, `AZN.L` — quarterly data is included automatically |
| **FMP** (optional) | Backup when Yahoo quarterly is empty | Set `FMP_API_KEY` in `.env` |
| **SEC 20-F** | Foreign companies with US listing | Not implemented as spreadsheets; use annual PDF via SEC if needed |

Keep the **home exchange suffix** on tickers in your sheet (e.g. `IFX.DE` not bare `IFX`).

Each ticker gets its own subfolder on Drive.

## One-time setup

### 1. Python environment

```bash
cd stock-financials
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if tickers are not in column A or if the first row is a header (defaults are already set for your sheet/folder URLs).

### 2. Google Cloud credentials

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick an existing one).
3. Enable **Google Sheets API** and **Google Drive API**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app**.
5. Download JSON and save as `credentials.json` in this folder.
6. **OAuth consent screen**: add your Google account as a test user (if the app is in "Testing" mode).

### 3. SEC EDGAR (for 10-K downloads)

SEC requires a contact email in requests. Set in `.env`:

```
SEC_EMAIL=you@example.com
```

### 4. Sheet column

If tickers are not in column **A**, set `TICKER_COLUMN` in `.env` (0 = A, 1 = B, …). If the first row is a header, keep `DATA_START_ROW=1`.

## Run

```bash
source .venv/bin/activate
python main.py
```

First run opens a browser to sign in to Google and grant access to read the spreadsheet and upload files to Drive.

### Options

```bash
# Test one symbol without touching the sheet
python main.py --tickers AAPL

# Save locally only (no Drive upload)
python main.py --local-only

# Skip SEC 10-K (faster; non-US stocks)
python main.py --no-10k
```

Local copies are under `./output/{TICKER}/`.

## Analysis tips (long-term quality)

Use the **overview** sheet and statements to check:

- **Profitability**: profit margins, ROE trending up over years
- **Balance sheet**: debt/equity reasonable vs peers; cash vs debt
- **Cash flow**: free cash flow positive and growing; FCF vs net income
- **Valuation**: trailing/forward P/E vs history and sector (overview sheet)
- **10-K**: business model, risks, competition (qualitative)

This tool does not give buy/sell advice; it automates gathering data so you can judge quality yourself.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Missing credentials.json` | Complete Google Cloud step 2 |
| `No tickers found` | Adjust `TICKER_COLUMN` / `DATA_START_ROW` in `.env` |
| Empty Excel for a ticker | Symbol may be wrong, delisted, or not on Yahoo; try `--tickers` with a known US symbol |
| 10-K fails | US listings only; set `DOWNLOAD_10K=false` or `--no-10k` for foreign tickers |
| Drive upload denied | Sign in with the account that owns the target folder |

## Privacy

`token.json` stores your OAuth token locally. Do not commit `credentials.json`, `token.json`, or `.env`.
