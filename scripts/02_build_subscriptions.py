"""
Step 2 — Build the monthly subscription snapshot from the transaction log.

A user's state at month-end E comes from their latest transaction on or
before E (ordered by transaction_date, then cancels last):
  - active  if E falls inside that transaction's coverage
  - coverage = [transaction_date, membership_expire_date], extended up to the
    next transaction when the user renews within GRACE_DAYS of expiry
    (Kaggle's churn rule — a renewal a few days late is not churn + return)
  - a cancel transaction moves the end date to its membership_expire_date

MRR (NTD, monthly-normalised):
  actual_amount_paid / plan months, where 28–31 day plans count as exactly
  1 month (so a 31-day plan at 149 NTD is 149, not 144.2) and longer plans
  as days / 30. Free / promo memberships are active with 0 MRR.
  A cancel keeps the MRR of the plan it cancels until access ends.

Output:
  KKBOX_DIR/parquet/snapshot.parquet  one row per user per active month (large)
  output/monthly_summary.csv          users / MRR / flows per month (for review)
"""

import time

import duckdb

from config import DATA_END, GRACE_DAYS, OUTPUT, PARQUET_DIR, parquet

t0 = time.time()
con = duckdb.connect()
con.execute("SET memory_limit = '10GB'")
con.execute(f"SET temp_directory = '{(PARQUET_DIR / '_tmp').as_posix()}'")

con.execute(f"""
CREATE TEMP TABLE tx AS
SELECT msno, transaction_date, membership_expire_date AS expire_date,
       is_cancel, is_auto_renew, payment_method_id,
       actual_amount_paid AS paid, plan_list_price,
       CASE WHEN payment_plan_days > 0 THEN payment_plan_days
            ELSE membership_expire_date - transaction_date END AS plan_days
FROM '{parquet('transactions')}'
-- Step 1 decisions: drop rows whose dates cannot form a coverage period
WHERE membership_expire_date BETWEEN DATE '2015-01-01' AND DATE '2018-12-31'
  AND (is_cancel OR membership_expire_date >= transaction_date)
""")

con.execute(f"""
CREATE TEMP TABLE states AS
WITH ordered AS (
    SELECT *,
        CASE WHEN is_cancel THEN NULL
             WHEN paid > 0 AND plan_days > 0
                THEN paid / CASE WHEN plan_days BETWEEN 28 AND 31 THEN 1 ELSE plan_days / 30.0 END
             ELSE 0 END AS tx_mrr,
        lead(transaction_date) OVER w AS next_date
    FROM tx
    WINDOW w AS (PARTITION BY msno ORDER BY transaction_date, is_cancel, expire_date)
),
filled AS (
    SELECT *,
        -- a cancel row inherits the plan it cancels
        last_value(tx_mrr IGNORE NULLS) OVER w AS mrr,
        last_value(CASE WHEN NOT is_cancel THEN plan_days END IGNORE NULLS) OVER w AS cur_plan_days,
        last_value(CASE WHEN NOT is_cancel THEN payment_method_id END IGNORE NULLS) OVER w AS cur_payment_method,
        last_value(CASE WHEN NOT is_cancel THEN is_auto_renew END IGNORE NULLS) OVER w AS cur_auto_renew,
        last_value(CASE WHEN NOT is_cancel THEN paid < plan_list_price END IGNORE NULLS) OVER w AS cur_discounted
    FROM ordered
    WINDOW w AS (PARTITION BY msno ORDER BY transaction_date, is_cancel, expire_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT *,
    least(
        CASE WHEN next_date IS NOT NULL AND next_date <= expire_date + {GRACE_DAYS}
             THEN next_date - 1 ELSE expire_date END,
        coalesce(next_date - 1, DATE '{DATA_END}'),
        DATE '{DATA_END}'
    ) AS covered_until
FROM filled
""")

# One row per (user, month) whose month-end falls inside a state's coverage.
con.execute(f"""
COPY (
    WITH months AS (
        SELECT msno, unnest(generate_series(
                   date_trunc('month', transaction_date),
                   date_trunc('month', covered_until + INTERVAL 1 DAY) - INTERVAL 1 MONTH,
                   INTERVAL 1 MONTH))::DATE AS month,
               coalesce(mrr, 0) AS mrr, is_cancel AS cancel_pending,
               cur_plan_days AS plan_days, cur_payment_method AS payment_method_id,
               cur_auto_renew AS is_auto_renew, coalesce(cur_discounted, false) AS is_discounted
        FROM states
        WHERE covered_until >= transaction_date
    )
    SELECT *, min(month) OVER (PARTITION BY msno) AS cohort_month
    FROM months
) TO '{parquet('snapshot')}' (FORMAT parquet, COMPRESSION zstd)
""")

S = f"'{parquet('snapshot')}'"
summary = con.execute(f"""
WITH s AS (SELECT msno, month, mrr, cohort_month FROM {S}),
flows AS (
    SELECT coalesce(c.month, p.month + INTERVAL 1 MONTH)::DATE AS month,
           c.msno IS NOT NULL AND p.msno IS NULL AND c.month = c.cohort_month AS is_new,
           c.msno IS NOT NULL AND p.msno IS NULL AND c.month > c.cohort_month AS is_reactivated,
           c.msno IS NULL AS is_churned
    FROM s c FULL JOIN s p ON c.msno = p.msno AND c.month = p.month + INTERVAL 1 MONTH
)
SELECT a.month,
       a.active_users, a.paying_users, round(a.mrr) AS mrr_ntd,
       f.new_users, f.reactivated_users, f.churned_users
FROM (SELECT month, count(*) AS active_users, count(*) FILTER (WHERE mrr > 0) AS paying_users,
             sum(mrr) AS mrr FROM s GROUP BY 1) a
JOIN (SELECT month, count(*) FILTER (WHERE is_new) AS new_users,
             count(*) FILTER (WHERE is_reactivated) AS reactivated_users,
             count(*) FILTER (WHERE is_churned) AS churned_users
      FROM flows GROUP BY 1) f USING (month)
ORDER BY month
""").df()

OUTPUT.mkdir(exist_ok=True)
summary.to_csv(OUTPUT / "monthly_summary.csv", index=False)
n_rows, n_users = con.execute(f"SELECT count(*), count(DISTINCT msno) FROM {S}").fetchone()
print(f"snapshot: {n_rows:,} user-months, {n_users:,} users ({time.time() - t0:.0f}s)")
print(summary.to_string(index=False))
