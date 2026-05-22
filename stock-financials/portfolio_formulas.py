"""Portfolio sheet formulas for Numbers (AppleScript) and Excel (openpyxl)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from config import PORTFOLIO_DATA_START_ROW, PORTFOLIO_SHEET_NAME
from numbers_parser.xrefs import xl_rowcol_to_cell
from portfolio_positions import PORTFOLIO_EXPORT_COLUMNS

logger = logging.getLogger(__name__)

# 0-based column index — portfolio sheet A–P layout
COL_SHARES = PORTFOLIO_EXPORT_COLUMNS.index("Shares [units]")
COL_BUY_PRICE = PORTFOLIO_EXPORT_COLUMNS.index("Buy Price [local]")
COL_TOTAL_FEES = PORTFOLIO_EXPORT_COLUMNS.index("Total Fees [local]")
COL_INVESTMENT = PORTFOLIO_EXPORT_COLUMNS.index("Investment [local]")
COL_OPEN_FX = PORTFOLIO_EXPORT_COLUMNS.index("Open Exchange Rate [EUR→local]")
COL_INVESTMENT_EUR = PORTFOLIO_EXPORT_COLUMNS.index("Investment [EUR]")
COL_PRICE = PORTFOLIO_EXPORT_COLUMNS.index("Price [local]")
COL_VALUE = PORTFOLIO_EXPORT_COLUMNS.index("Value [local]")
COL_EXCHANGE_RATE = PORTFOLIO_EXPORT_COLUMNS.index("Exchange Rate [EUR→local]")
COL_VALUE_EUR = PORTFOLIO_EXPORT_COLUMNS.index("Value [EUR]")


def investment_formula(zero_based_row: int) -> str:
    shares = xl_rowcol_to_cell(zero_based_row, COL_SHARES)
    price = xl_rowcol_to_cell(zero_based_row, COL_BUY_PRICE)
    fees = xl_rowcol_to_cell(zero_based_row, COL_TOTAL_FEES)
    return f"={shares}*{price}-{fees}"


def investment_eur_formula(zero_based_row: int) -> str:
    inv = xl_rowcol_to_cell(zero_based_row, COL_INVESTMENT)
    fx = xl_rowcol_to_cell(zero_based_row, COL_OPEN_FX)
    return f"={inv}/{fx}"


def value_formula(zero_based_row: int) -> str:
    shares = xl_rowcol_to_cell(zero_based_row, COL_SHARES)
    price = xl_rowcol_to_cell(zero_based_row, COL_PRICE)
    return f"={shares}*{price}"


def value_eur_formula(zero_based_row: int) -> str:
    value = xl_rowcol_to_cell(zero_based_row, COL_VALUE)
    fx = xl_rowcol_to_cell(zero_based_row, COL_EXCHANGE_RATE)
    return f"={value}/{fx}"


def apply_portfolio_formulas_openpyxl(ws, num_data_rows: int) -> None:
    """Write Excel formulas for computed portfolio columns."""
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
        ws.cell(row=row_idx, column=COL_VALUE + 1, value=value_formula(zero_row))
        ws.cell(row=row_idx, column=COL_VALUE_EUR + 1, value=value_eur_formula(zero_row))


def apply_portfolio_formulas_numbers(
    path: Path,
    *,
    portfolio_sheet: str = PORTFOLIO_SHEET_NAME,
    num_data_rows: int,
) -> bool:
    """Set portfolio formulas in Numbers via AppleScript."""
    if num_data_rows <= 0:
        return True

    path = path.expanduser().resolve()
    start_row = PORTFOLIO_DATA_START_ROW
    end_row = start_row + num_data_rows - 1
    inv_col = COL_INVESTMENT + 1
    eur_col = COL_INVESTMENT_EUR + 1
    value_col = COL_VALUE + 1
    value_eur_col = COL_VALUE_EUR + 1

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
        formulas = (
            (inv_col, investment_formula(zero_row)),
            (eur_col, investment_eur_formula(zero_row)),
            (value_col, value_formula(zero_row)),
            (value_eur_col, value_eur_formula(zero_row)),
        )
        for col, formula in formulas:
            escaped = formula.replace('"', '\\"')
            lines.append(
                f'        set value of cell {col} of row {row} to "{escaped}"'
            )
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
            timeout=180,
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
