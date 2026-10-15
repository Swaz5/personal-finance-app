"""Where the app reads its data from. Two modes:

- Real (default): data/finance.db, statements in data/statements/,
  accounts + CSV mappings in config/. data/ is gitignored.
- Demo (FINANCE_DEMO=1, set by `python demo.py`): data/demo.db, built
  from synthetic statements generated into data/demo/statements/, with
  the demo/ folder's accounts and mappings.

FINANCE_DB_PATH overrides the database file in either mode (used by tests).
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DEMO_DIR = REPO_ROOT / "demo"

DEMO_MODE = os.environ.get("FINANCE_DEMO") == "1"

if DEMO_MODE:
    DB_PATH = DATA_DIR / "demo.db"
    STATEMENTS_DIR = DATA_DIR / "demo" / "statements"
    MAPPINGS_DIR = DEMO_DIR / "mappings"
    ACCOUNTS_CONFIG = DEMO_DIR / "accounts.yaml"
else:
    DB_PATH = DATA_DIR / "finance.db"
    STATEMENTS_DIR = DATA_DIR / "statements"
    MAPPINGS_DIR = REPO_ROOT / "config" / "mappings"
    ACCOUNTS_CONFIG = REPO_ROOT / "config" / "accounts.yaml"

if os.environ.get("FINANCE_DB_PATH"):
    DB_PATH = Path(os.environ["FINANCE_DB_PATH"])
