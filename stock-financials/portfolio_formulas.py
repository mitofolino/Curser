"""Portfolio sheet formulas for Numbers (AppleScript) and Excel (openpyxl)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from config import PORTFOLIO_DATA_START_ROW, PORTFOLIO_SHEET_NAME
from numbers_parser.xrefs import xl_rowcol_to_cell
from portfolio_positions import PORTFOLIO_EXPORT_COLUMNS

logger = logging.getLogger(__name__)

# 0-based column index in export table
COL_SHARES = PORTFOLIO_EXPORT_COLUMNS.index("Shares [units]")
COL_BUY_PRICE = PORTFOLIO_EXPORT_COLUMNS.index("Buy Price [local]")
COL_TOTAL_FEES = PORTFOLIO_EXPORT_COLUMNS.index("Total Fees [local]")
COL_INVESTMENT = PORTFOLIO_EXPORT_COLUMNS.index("Investment [local]")
COL_OPEN_FX = PORTFOLIO_EXPORT_COLUMNS.index("Open Exchange Rate [EUR→local]")
COL_INVESTMENT_EUR = PORTFOLIO_EXPORT_COLUMNS.index("Investment [EUR]")


def _excel_row(zero_based_row: int) -> int:
    return zero_based_row + 1


def investment_formula(zero_based_row: int) -> str:
    r = _excel_row(zero_based_row)
    shares = xl_rowcol_to_cell(zero_based_row, COL_SHARES)
    price = xl_rowcol_to_cell(zero_based_row, COL_BUY_PRICE)
    fees = xl_rowcol_to_cell(zero_based_row, COL_TOTAL_FEES)
    return f"={shares}*{price}-{fees}"


def investment_eur_formula(zero_based_row: int) -> str:
    inv = xl_rowcol_to_cell(zero_based_row, COL_INVESTMENT)
    fx = xl_rowcol_to_cell(zero_based_row, COL_OPEN_FX)
    return f"={inv}/{fx}"


def apply_portfolio_formulas_openpyxl(ws, num_data_rows: int) -> None:
    """Write Excel formulas for Investment and Investment [EUR] columns."""
    start = PORTFOLIO_DATA_START_ROW
    for i in range(num_data_rows):
        row_idx = start + i
        zero_row = row_idx - 1
        ws.cell(row=row_idx, column=COL_INVESTMENT + 1, value=investment_formula(zero_row))
        ws.cell(
            row=row_idx,
            column=COL_INVESTMENT_EUR + 1,
            value=investment_eur_formula(zero_row),
        )


def apply_portfolio_formulas_numbers(
    path: Path,
    *,
    portfolio_sheet: str = PORTFOLIO_SHEET_NAME,
    num_data_rows: int,
) -> bool:
    """
    Set Investment formulas in Numbers via AppleScript (value strings starting with '=').
    Returns True if the script ran successfully.
    """
    if num_data_rows <= 0:
        return True

    path = path.expanduser().resolve()
    start_row = PORTFOLIO_DATA_START_ROW
    end_row = start_row + num_data_rows - 1
    inv_col = COL_INVESTMENT + 1
    eur_col = COL_INVESTMENT_EUR + 1

    lines = [
        'tell application "Numbers"',
        f'  set docRef to open POSIX file "{path}"',
        "  delay 0.5",
        "  tell docRef",
        f'    tell sheet "{portfolio_sheet}"',
        "      tell table 1",
    ]
    for row in range(start_row, end_row + 1):
        zero_row = row - 1
        inv_formula = investment_formula(zero_row).replace('"', '\\"')
        eur_formula = investment_eur_formula(zero_row).replace('"', '\\"')
        lines.append(f'        set value of cell {inv_col} of row {row} to "{inv_formula}"')
        lines.append(f'        set value of cell {eur_col} of row {row} to "{eur_formula}"')
    lines += [
        "      end tell",
        "    end tell",
        "  end tell",
        "  save docRef",
        "  close docRef",
        "end tell",
    ]

    script = "\n".join(lines)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        logger.info(
            "Applied portfolio formulas in Numbers (%d row(s), sheet %s)",
            num_data_rows,
            portfolio_sheet,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Numbers formula AppleScript failed: %s", e)
        return False
