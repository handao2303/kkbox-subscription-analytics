"""
Step 0 — Ingest the raw KKBox CSVs into typed Parquet.

Every later step reads Parquet through DuckDB, never the CSVs: the raw
files total ~32 GB and ~420M rows, so pandas cannot hold them in memory.

What this step does (and nothing more — cleaning decisions live in Step 1):
  - parses YYYYMMDD integers into DATEs
  - unions v1 + v2 transactions, dropping exact duplicate rows (v2 re-ships
    part of v1's period)
  - unions v1 + v2 user logs as-is: v1 ends 2017-02-28 and v2 covers March
    2017 only, so they cannot overlap (a DISTINCT over ~410M rows needs >10 GB RAM)
  - keeps the two churn label sets separate: train_v1 labels Feb 2017
    expiries, train_v2 labels Mar 2017 expiries

Output: KKBOX_DIR/parquet/{members,transactions,user_logs,train_v1,train_v2}.parquet

Usage: python scripts/00_ingest.py [table ...]   (default: all; existing files are skipped)
"""

import sys
import time

from config import PARQUET_DIR, RAW, connect, parquet

DATE = "strptime(CAST({c} AS VARCHAR), '%Y%m%d')::DATE"

SELECTS = {
    "members": f"""
        SELECT msno, city, bd, NULLIF(gender, '') AS gender, registered_via,
               {DATE.format(c='registration_init_time')} AS registration_date
        FROM {{src}}""",
    "transactions": f"""
        SELECT DISTINCT msno, payment_method_id, payment_plan_days,
               plan_list_price, actual_amount_paid,
               is_auto_renew::BOOLEAN AS is_auto_renew,
               {DATE.format(c='transaction_date')} AS transaction_date,
               {DATE.format(c='membership_expire_date')} AS membership_expire_date,
               is_cancel::BOOLEAN AS is_cancel
        FROM {{src}}""",
    "user_logs": f"""
        SELECT msno, {DATE.format(c='date')} AS date,
               num_25, num_50, num_75, num_985, num_100, num_unq, total_secs
        FROM {{src}}""",
    "train_v1": "SELECT msno, is_churn::BOOLEAN AS is_churn FROM {src}",
    "train_v2": "SELECT msno, is_churn::BOOLEAN AS is_churn FROM {src}",
}


def ingest(con, name):
    out = PARQUET_DIR / f"{name}.parquet"
    if out.exists():
        print(f"  {name}: exists, skipped")
        return
    files = [p for p in RAW[name] if p.exists()]
    missing = [p.name for p in RAW[name] if not p.exists()]
    if not files:
        print(f"  {name}: no raw file found, skipped")
        return
    if missing:
        print(f"  {name}: WARNING missing {missing}, ingesting the rest")

    src = "read_csv([{}], header=true, union_by_name=true)".format(
        ", ".join(f"'{p.as_posix()}'" for p in files)
    )
    t0 = time.time()
    tmp = out.with_suffix(".tmp")
    con.execute(
        f"COPY ({SELECTS[name].format(src=src)}) TO '{tmp.as_posix()}' "
        "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)"
    )
    tmp.replace(out)
    rows = con.execute(f"SELECT count(*) FROM '{parquet(name)}'").fetchone()[0]
    print(f"  {name}: {rows:,} rows in {time.time() - t0:.0f}s")


def main():
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    con = connect("00")

    names = sys.argv[1:] or list(SELECTS)
    print(f"Ingesting into {PARQUET_DIR}")
    for name in names:
        ingest(con, name)


if __name__ == "__main__":
    main()
