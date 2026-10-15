"""
Shared paths for the KKBox pipeline.

Raw data lives outside the repo (too large for git). Override the default
location with the KKBOX_DIR environment variable.

  KKBOX_DIR/csv      extracted Kaggle CSVs (kaggle competitions download ...)
  KKBOX_DIR/parquet  written by 00_ingest.py, read by every later step
"""

import os
from pathlib import Path

KKBOX_DIR = Path(os.environ.get("KKBOX_DIR", r"D:\datasets\kkbox"))
CSV_DIR = KKBOX_DIR / "csv"
PARQUET_DIR = KKBOX_DIR / "parquet"

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

# v2 files ship in a nested folder inside their .7z archives.
V2_DIR = CSV_DIR / "data" / "churn_comp_refresh"

RAW = {
    "members": [CSV_DIR / "members_v3.csv"],
    "transactions": [CSV_DIR / "transactions.csv", V2_DIR / "transactions_v2.csv"],
    "user_logs": [CSV_DIR / "user_logs.csv", V2_DIR / "user_logs_v2.csv"],
    "train_v1": [CSV_DIR / "train.csv"],
    "train_v2": [V2_DIR / "train_v2.csv"],
}


# Last transaction in the data. Churn needs a 30-day look-ahead past expiry,
# so the last month whose churn is fully observable is Feb 2017.
DATA_END = "2017-03-31"
# No transactions before Jan 2015: long plans bought earlier are invisible,
# so the first 6 months are a warm-up and are not reported.
REPORT_START = "2015-07-01"
REPORT_END = "2017-02-01"
GRACE_DAYS = 30  # Kaggle churn rule: no renewal within 30 days of expiry


def parquet(name: str) -> str:
    """Path to an ingested table, as a string DuckDB can read."""
    return (PARQUET_DIR / f"{name}.parquet").as_posix()
