# Stock financials downloader

Reads ticker symbols from **`Stocks.xlsx`** and downloads financial data for long-term investment analysis into a local folder on your Mac.

Default paths:

- **Tickers:** `/Users/mitjarebec/Documents/Stocks_Analyses/Stocks.xlsx`
- **Output:** `/Users/mitjarebec/Documents/Stocks_Analyses/`

## Folder layout

```
Stocks_Analyses/
├── Stocks.xlsx                 ← your ticker list (column A)
├── portfolio_summary.xlsx      ← generated metrics + EUR columns
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
Only periods within the **last 2 years** are exported (`STATEMENT_YEARS` in `.env`).

## What gets downloaded (per ticker)

| File pattern | Source | Contents |
|--------------|--------|----------|
| `{TICKER}_{date}_income_statement_*.xlsx` | Yahoo Finance | Income statement (annual / quarterly) |
| `{TICKER}_{date}_balance_sheet_*.xlsx` | Yahoo Finance | Balance sheet |
| `{TICKER}_{date}_cash_flow_*.xlsx` | Yahoo Finance | Cash flow |
| `{TICKER}_{date}_company_overview.xlsx` | Yahoo Finance | Key metrics |
| `{TICKER}_{date}_etf_overview.xlsx` | Yahoo Finance | ETFs only |
| `{TICKER}_{date}_10_K_*.html` / `20_F_*` | SEC EDGAR | Last 2 annual filings (stocks) |
| **`portfolio_summary.xlsx`** | Generated | All tickers; amounts in local currency **and EUR** |

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

## Privacy / Git

Do **not** commit `.env`, `credentials.json`, `token.json`, or your `Stocks_Analyses/` data. They are listed in `.gitignore`.
