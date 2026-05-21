"""Remove legacy layouts (statements/, sec/, old combined workbooks)."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from config import OUTPUT_DIR

logger = logging.getLogger(__name__)

LEGACY_SUBFOLDERS = frozenset({"statements", "sec", ".sec_tmp"})
LEGACY_FILE_PATTERNS = (
    re.compile(r"^.+_financials\.xlsx$", re.I),
    re.compile(r"^.+_etf_overview\.xlsx$", re.I),
)
NEW_FILE_PATTERN = re.compile(
    r"^[A-Z0-9.]+\_\d{4}-\d{2}-\d{2}\_.+\.(xlsx|html|txt)$", re.I
)


def _is_legacy_file(name: str) -> bool:
    if NEW_FILE_PATTERN.match(name):
        return False
    lower = name.lower()
    if any(p.match(name) for p in LEGACY_FILE_PATTERNS):
        return True
    if lower.endswith(".xlsx") and "financials" in lower:
        return True
    return False


def cleanup_local_output(root: Path = OUTPUT_DIR) -> int:
    if not root.exists():
        return 0
    removed = 0
    for ticker_path in root.iterdir():
        if not ticker_path.is_dir():
            continue
        for child in list(ticker_path.iterdir()):
            if child.is_dir() and child.name in LEGACY_SUBFOLDERS:
                shutil.rmtree(child)
                removed += 1
                logger.info("Removed %s", child)
            elif child.is_dir() and (
                child.name.startswith("SEC") or child.name == "sec"
            ):
                shutil.rmtree(child)
                removed += 1
            elif child.is_file() and _is_legacy_file(child.name):
                child.unlink()
                removed += 1
                logger.info("Removed %s", child)
    logger.info("Cleanup: removed %d legacy path(s)", removed)
    return removed
