"""
Step 3 — SaaS metrics from the monthly snapshot.

Every metric is built from one transition table: each user's state at the end
of month M-1 (prev) vs month M (cur). "Paying" = active with MRR > 0.

Churn definitions (agreed in KKBOX-5):
  - logo churn       active at M-1, gone at M (Kaggle rule, 30-day grace)
  - paid churn       paying at M-1, gone at M
  - billing gap      a paid churn that belongs to a mass outage of one payment
                     method AND that user came back on the same method within
                     6 months. Kept in paid churn (Kaggle rule), also reported
                     excluded (`paid_churn_ex_gap`).
  - trial            users whose first active month is free; tracked as a
                     conversion rate, never mixed into paid churn.

Outputs (output/):
  mrr_waterfall.csv        MRR bridge per month: new, reactivation, expansion,
                           contraction, churn (billing gap / other)
  churn_rate_by_month.csv  logo / paid / paid ex-gap / revenue churn, NRR
  billing_gap_episodes.csv detected outages by payment method
  churn_type_by_month.csv  paid churn split: cancelled / auto-renew lapse / manual non-renewal
  trial_conversion.csv     trial cohorts and % that pay within 3 months
  cohort_retention.csv     % of each first-paid cohort still paying, by month since start
  ltv_by_segment.csv       ARPU, churn ex-gap and LTV by segment
"""

import time

from config import OUTPUT, PARQUET_DIR, REPORT_END, REPORT_START, connect, parquet

# Mass-outage rule: a (payment method, month) whose paid churn is at least
# GAP_MULTIPLE x its usual level, at least GAP_MIN_USERS users, and where most
# churners come back on the same method within GAP_RETURN_MONTHS.
GAP_MULTIPLE = 3
GAP_MIN_USERS = 5000
GAP_MIN_RETURN_SHARE = 0.5
GAP_RETURN_MONTHS = 6
TRIAL_WINDOW_MONTHS = 3

t0 = time.time()
con = connect("03")
S, M = f"'{parquet('snapshot')}'", f"'{parquet('members')}'"
W = f"BETWEEN DATE '{REPORT_START}' AND DATE '{REPORT_END}'"


def save(name, sql):
    df = con.execute(sql).df()
    df.to_csv(OUTPUT / f"{name}.csv", index=False)
    print(f"  {name}.csv: {len(df):,} rows")
    return df


con.execute(f"""
CREATE TEMP TABLE snap AS
SELECT s.*,
       (month + INTERVAL 1 MONTH)::DATE AS next_month,
       min(CASE WHEN mrr > 0 THEN month END) OVER (PARTITION BY msno) AS first_paid_month
FROM {S} s
""")

TR_CACHE = PARQUET_DIR / "transitions.parquet"
cache_ok = TR_CACHE.exists() and TR_CACHE.stat().st_mtime > (PARQUET_DIR / "snapshot.parquet").stat().st_mtime

if cache_ok:
    # The transition table is the slow part (minutes); reuse it while the
    # snapshot is unchanged.
    print("  reusing cached transitions.parquet")
    con.execute(f"CREATE TEMP TABLE tr AS SELECT * FROM '{TR_CACHE.as_posix()}'")
else:
    # Next month the user is active again after a gap, and on which method.
    con.execute("""
    CREATE TEMP TABLE returns AS
    SELECT msno, month, payment_method_id,
           lead(month) OVER w AS next_active_month,
           lead(payment_method_id) OVER w AS next_method
    FROM snap
    WINDOW w AS (PARTITION BY msno ORDER BY month)
    """)

    # Transition table: one row per user per month where they were active at
    # M-1 and/or M. prev_* describe the user at M-1 (segment attributes too).
    con.execute(f"""
    CREATE TEMP TABLE tr0 AS
    SELECT coalesce(c.month, p.next_month) AS month,
           coalesce(c.msno, p.msno) AS msno,
           coalesce(p.mrr, 0) AS prev_mrr, coalesce(c.mrr, 0) AS cur_mrr,
           p.msno IS NOT NULL AS prev_active, c.msno IS NOT NULL AS cur_active,
           p.cancel_pending AS prev_cancel_pending, p.is_auto_renew AS prev_auto_renew,
           p.payment_method_id AS prev_method, p.plan_days AS prev_plan_days,
           coalesce(c.cohort_month, p.cohort_month) AS cohort_month,
           coalesce(c.first_paid_month, p.first_paid_month) AS first_paid_month,
           r.next_active_month, r.next_method
    FROM snap c
    FULL JOIN snap p ON c.msno = p.msno AND c.month = p.next_month
    LEFT JOIN returns r ON r.msno = p.msno AND r.month = p.month
    WHERE coalesce(c.month, p.next_month) {W}
    """)

    # --- billing-gap detection ---------------------------------------------
    con.execute(f"""
    CREATE TEMP TABLE paid_churn AS
    SELECT msno, month, prev_method,
           next_active_month IS NOT NULL
             AND next_active_month <= month + INTERVAL {GAP_RETURN_MONTHS} MONTH
             AND next_method = prev_method AS returned_same_method
    FROM tr0 WHERE prev_mrr > 0 AND NOT cur_active
    """)
    episodes = save("billing_gap_episodes", f"""
    WITH by_m AS (
        SELECT prev_method AS payment_method_id, month, count(*) AS churned,
               avg(returned_same_method::INT) AS return_share
        FROM paid_churn GROUP BY 1, 2
    ),
    base AS (
        SELECT *, median(churned) OVER (PARTITION BY payment_method_id) AS usual_churn FROM by_m
    )
    SELECT payment_method_id, month, churned, round(usual_churn) AS usual_churn,
           round(churned / usual_churn, 1) AS multiple, round(return_share, 3) AS return_share
    FROM base
    WHERE churned >= {GAP_MIN_USERS} AND churned >= {GAP_MULTIPLE} * usual_churn
      AND return_share >= {GAP_MIN_RETURN_SHARE}
    ORDER BY month, payment_method_id
    """)
    con.register("episodes_df", episodes)
    con.execute(f"""
    COPY (
        SELECT tr0.*, g.msno IS NOT NULL AS is_billing_gap
        FROM tr0 LEFT JOIN (
            SELECT pc.msno, pc.month FROM paid_churn pc
            JOIN episodes_df e ON e.payment_method_id = pc.prev_method AND e.month = pc.month
            WHERE pc.returned_same_method
        ) g USING (msno, month)
    ) TO '{TR_CACHE.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
    """)
    con.execute("DROP TABLE tr0; DROP TABLE returns; DROP TABLE paid_churn")
    con.execute(f"CREATE TEMP TABLE tr AS SELECT * FROM '{TR_CACHE.as_posix()}'")

# --- MRR waterfall ---------------------------------------------------------
save("mrr_waterfall", """
SELECT month,
    round(sum(prev_mrr)) AS starting_mrr,
    round(sum(cur_mrr) FILTER (WHERE prev_mrr = 0 AND month = first_paid_month)) AS new_mrr,
    round(sum(cur_mrr) FILTER (WHERE prev_mrr = 0 AND month > first_paid_month)) AS reactivation_mrr,
    round(sum(cur_mrr - prev_mrr) FILTER (WHERE prev_mrr > 0 AND cur_mrr > prev_mrr)) AS expansion_mrr,
    -- includes paying -> free promo while still active
    round(-sum(prev_mrr - cur_mrr) FILTER (WHERE prev_mrr > 0 AND cur_mrr < prev_mrr AND cur_active)) AS contraction_mrr,
    round(-sum(prev_mrr) FILTER (WHERE prev_mrr > 0 AND NOT cur_active AND is_billing_gap)) AS churn_billing_gap_mrr,
    round(-sum(prev_mrr) FILTER (WHERE prev_mrr > 0 AND NOT cur_active AND NOT is_billing_gap)) AS churn_other_mrr,
    round(sum(cur_mrr)) AS ending_mrr
FROM tr GROUP BY 1 ORDER BY 1
""")

# --- churn rates and NRR ---------------------------------------------------
save("churn_rate_by_month", """
SELECT month,
    count(*) FILTER (WHERE prev_active) AS active_start,
    count(*) FILTER (WHERE prev_mrr > 0) AS paying_start,
    round(count(*) FILTER (WHERE prev_active AND NOT cur_active)
          / count(*) FILTER (WHERE prev_active), 4) AS logo_churn,
    round(count(*) FILTER (WHERE prev_mrr > 0 AND NOT cur_active)
          / count(*) FILTER (WHERE prev_mrr > 0), 4) AS paid_churn,
    round(count(*) FILTER (WHERE prev_mrr > 0 AND NOT cur_active AND NOT is_billing_gap)
          / count(*) FILTER (WHERE prev_mrr > 0 AND NOT is_billing_gap), 4) AS paid_churn_ex_gap,
    count(*) FILTER (WHERE is_billing_gap) AS billing_gap_users,
    round(sum(prev_mrr) FILTER (WHERE prev_mrr > 0 AND NOT cur_active)
          / sum(prev_mrr), 4) AS revenue_churn,
    -- NRR: this month's MRR from users who were paying last month / their MRR last month
    round(sum(cur_mrr) FILTER (WHERE prev_mrr > 0) / sum(prev_mrr), 4) AS nrr
FROM tr GROUP BY 1 ORDER BY 1
""")

# --- why paid users leave --------------------------------------------------
save("churn_type_by_month", """
SELECT month,
    CASE WHEN is_billing_gap THEN 'billing gap'
         WHEN prev_cancel_pending THEN 'cancelled by user'
         WHEN prev_auto_renew THEN 'auto-renew lapsed'
         ELSE 'manual plan not renewed' END AS churn_type,
    count(*) AS users, round(sum(prev_mrr)) AS lost_mrr
FROM tr WHERE prev_mrr > 0 AND NOT cur_active
GROUP BY 1, 2 ORDER BY 1, 2
""")

# --- trials ------------------------------------------------------------------
save("trial_conversion", f"""
WITH trials AS (
    SELECT msno, cohort_month, first_paid_month FROM snap
    WHERE month = cohort_month AND mrr = 0 AND cohort_month {W}
)
SELECT cohort_month AS month, count(*) AS trial_starts,
    count(*) FILTER (WHERE first_paid_month <= cohort_month + INTERVAL {TRIAL_WINDOW_MONTHS} MONTH) AS converted,
    round(converted / trial_starts, 4) AS conversion_rate
FROM trials GROUP BY 1 ORDER BY 1
""")

# --- cohort retention (first-paid cohorts) -----------------------------------
save("cohort_retention", f"""
WITH cohorts AS (
    SELECT first_paid_month AS cohort, count(DISTINCT msno) AS cohort_size
    FROM snap WHERE first_paid_month {W} GROUP BY 1
)
SELECT s.first_paid_month AS cohort, c.cohort_size,
    datediff('month', s.first_paid_month, s.month) AS months_since_start,
    count(*) AS paying_users, round(count(*) / any_value(c.cohort_size), 4) AS retention
FROM snap s JOIN cohorts c ON c.cohort = s.first_paid_month
WHERE s.mrr > 0 AND s.month <= DATE '{REPORT_END}'
GROUP BY 1, 2, 3 ORDER BY 1, 3
""")

# --- LTV by segment ------------------------------------------------------------
# LTV = ARPU / monthly paid churn (ex billing gap), both over the report window.
con.execute(f"""
CREATE TEMP TABLE seg AS
SELECT t.prev_mrr, NOT t.cur_active AS churned,
    coalesce(m.registered_via::VARCHAR, 'unknown') AS registered_via,
    coalesce(m.city::VARCHAR, 'unknown') AS city,
    t.prev_method::VARCHAR AS payment_method,
    CASE WHEN t.prev_plan_days <= 31 THEN 'monthly (<=31d)'
         WHEN t.prev_plan_days <= 200 THEN 'multi-month (32-200d)'
         ELSE 'annual (>200d)' END AS plan_length,
    CASE WHEN t.prev_auto_renew THEN 'auto-renew' ELSE 'manual' END AS renewal
FROM tr t LEFT JOIN {M} m USING (msno)
WHERE t.prev_mrr > 0 AND NOT t.is_billing_gap
""")
dims = ["registered_via", "city", "payment_method", "plan_length", "renewal"]
save("ltv_by_segment", " UNION ALL ".join(f"""
SELECT '{d}' AS dimension, {d} AS segment,
    count(*) AS paying_user_months,
    round(avg(prev_mrr), 1) AS arpu_ntd,
    round(avg(churned::INT), 4) AS monthly_churn,
    round(avg(prev_mrr) / nullif(avg(churned::INT), 0)) AS ltv_ntd
FROM seg GROUP BY {d} HAVING count(*) >= 10000""" for d in dims)
    + " ORDER BY dimension, ltv_ntd DESC")

print(f"done in {time.time() - t0:.0f}s")
