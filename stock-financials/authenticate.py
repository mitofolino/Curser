#!/usr/bin/env python3
"""One-time Google sign-in. Saves token.json for main.py."""

import sys

from google_auth import get_credentials
from config import TOKEN_FILE

if __name__ == "__main__":
    print("Opening browser for Google sign-in...", flush=True)
    print("Allow access to Sheets (read) and Drive (upload).", flush=True)
    try:
        get_credentials()
    except Exception as e:
        err = str(e).lower()
        if "access_denied" in err or "access denied" in err:
            print(
                "\nSign-in was cancelled or blocked. Fix:\n"
                "  1. Google Cloud → OAuth consent screen → add your Gmail under Test users\n"
                "  2. On the warning screen, click Advanced → Go to StockFinancials (unsafe)\n"
                "  3. Click Allow for all permissions (do not cancel)\n"
                "Then run: python authenticate.py\n",
                flush=True,
            )
        raise SystemExit(1) from e
    print(f"Saved {TOKEN_FILE.resolve()}", flush=True)
    print("You can now run: python main.py", flush=True)
