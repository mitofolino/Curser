# Stock financials downloader

Reads ticker symbols from **`Stocks.xlsx`** and downloads financial data for long-term investment analysis into a local folder on your Mac.

Default paths:

- **Tickers:** `/Users/mitjarebec/Documents/Stocks_Analyses/Stocks.xlsx`
- **Output:** `/Users/mitjarebec/Documents/Stocks_Analyses/`

## Folder layout

```
Stocks_Analyses/
├── Stocks.xlsx                 ← your ticker list (column A)
├── portfolio_summary.numbers   ← main summary file (sheets: summary + portfolio)
├── portfolio_summary.xlsx      ← optional copy if PORTFOLIO_OUTPUT=xlsx or both
├── MSFT/
│   ├── MSFT_2024-09-30_income_statement_annual.xlsx
│   ├── MSFT_2024-06-30_income_statement_quarterly.xlsx
│   ├── MSFT_2026-05-21_company_overview.xlsx
│   ├── MSFT_2024-12-31_10_K_primary_document.html
│   └── ...
└── XLE/
    └── XLE_2026-05-21_etf_overview.xlsx
```

**Naming:** `{ticker}_{period_date}_{statement_type}.xlsx` (one period per file).  
Only periods within the **last N years** are exported (`STATEMENT_YEARS` in `.env`, default 5).

**Incremental runs:** existing statement and SEC files are never overwritten; only missing periods/files are added.

## What gets downloaded (per ticker)

| File pattern | Source | Contents |
|--------------|--------|----------|
| `{TICKER}_{date}_income_statement_*.xlsx` | Yahoo Finance | Income statement (annual / quarterly) |
| `{TICKER}_{date}_balance_sheet_*.xlsx` | Yahoo Finance | Balance sheet |
| `{TICKER}_{date}_cash_flow_*.xlsx` | Yahoo Finance | Cash flow |
| `{TICKER}_{date}_company_overview.xlsx` | Yahoo Finance | Key metrics |
| `{TICKER}_{date}_etf_overview.xlsx` | Yahoo Finance | ETFs only |
| `{TICKER}_{date}_10_K_*.html` / `20_F_*` | SEC EDGAR | Last N annual filings (`SEC_FILINGS_LIMIT`, default = `STATEMENT_YEARS`) |
| **`portfolio_summary.xlsx`** → `summary` | Generated | All tickers; amounts in local currency **and EUR** |
| **`portfolio_summary.xlsx`** → `portfolio` | eToro + IBKR API/CSV | Ticker, Full Name, Source, Currency, Shares, Open Date, Buy Price, Total Fees |

### Non-US / global companies

Use exchange suffixes in `Stocks.xlsx` (e.g. `IFX.DE`, `3750.HK`, `AZN.L`). ETFs `SWDA` / `IUSA` resolve to London listings automatically.

## Setup

```bash
cd stock-financials
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if tickers are not in column A or the first row is a header.

Set `SEC_EMAIL` in `.env` (required by SEC EDGAR for 10-K downloads).

## Run

```bash
source .venv/bin/activate
python main.py
```

### Options

```bash
python main.py --tickers MSFT AAPL
python main.py --no-10k
python main.py --cleanup   # remove old statements/ and sec/ subfolders
```

## Portfolio sheet (eToro + IBKR)

`portfolio_summary.numbers` (default) includes a **`portfolio`** table with columns:

`Ticker`, `Instrument Name`, `Broker`, `Currency`, `Shares [units]`, `Open Date [UTC]`, `Buy Price [local]`, `Total Fees [local]`, `Investment [local]` (= Shares × Buy Price − Fees), `Open Exchange Rate [EUR→local]` (Frankfurter rate on open date), `Investment [EUR]` (= Investment ÷ Open Exchange Rate), `Update Date [UTC]`

Configure brokers in `.env` (see `.env.example`). On each `python main.py` run, live positions are merged into that sheet.

Set `PORTFOLIO_OUTPUT=numbers` (default), `xlsx`, or `both` in `.env`. Per-ticker statement files remain `.xlsx` (Yahoo/Excel-friendly); only the **portfolio summary** uses Numbers when `numbers` or `both` is set.

### What you need to provide

| Broker | Option A (API) | Option B (CSV until API works) |
|--------|----------------|--------------------------------|
| **eToro** | `ETORO_ENABLED=true`, `ETORO_API_KEY`, correct `ETORO_API_URL` from eToro’s API docs for your account | Export positions CSV → `ETORO_CSV_PATH` |
| **IBKR** | `IBKR_ENABLED=true`, Client Portal / IB Gateway running, log in at `https://localhost:5000`, optional `IBKR_ACCOUNT_ID` | Flex/Activity export CSV → `IBKR_CSV_PATH` |

Also send (once): **exact API base URL and sample JSON** for eToro positions (or confirm you only want CSV), and whether IBKR uses **Client Portal** (port 5000) or **TWS API** (port 7496) — the code targets Client Portal by default.

## Privacy / Git

Do **not** commit `.env`, `credentials.json`, `token.json`, or your `Stocks_Analyses/` data. They are listed in `.gitignore`.
