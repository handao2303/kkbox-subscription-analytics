"""
Step 4 — Churn drivers and a churn-risk model.

Labels come from Kaggle: a user is churned if they do not renew within
30 days after their membership expires.
  - train_v1: users expiring in Feb 2017
  - train_v2: users expiring in Mar 2017

No leakage: features only use data up to the end of the month BEFORE the
expiry month, i.e. what the business would know one month ahead.
  - train set: train_v1, features cut at 2017-01-31
  - test set:  train_v2, features cut at 2017-02-28  (out-of-time validation)

Models: logistic regression (interpretable baseline) and histogram gradient
boosting (non-linear, handles missing values natively).

Outputs (output/):
  churn_driver_segments.csv    churn rate by segment on the test population
  churn_model_metrics.csv      ROC AUC, PR AUC, log loss, top-decile lift per model
  churn_feature_importance.csv permutation importance (gradient boosting)
  churn_risk_deciles.csv       actual churn by predicted-risk decile
"""

import time

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config import OUTPUT, PARQUET_DIR, connect, parquet

SEED = 2017
SPLITS = {"train": ("train_v1", "2017-01-31"), "test": ("train_v2", "2017-02-28")}

CATEGORICAL = ["last_payment_method", "registered_via", "city", "gender"]
NUMERIC = [
    "tenure_days", "n_transactions", "n_cancels", "n_payment_methods", "auto_renew_share",
    "last_plan_days", "last_paid", "last_list_price", "last_is_auto_renew", "last_is_cancel",
    "last_is_free", "last_is_discounted", "days_to_expire", "total_paid", "age",
    "registration_days", "active_days_30", "secs_30", "unq_30", "complete_share_30",
    "skip_share_30", "secs_trend", "days_since_last_listen",
]

t0 = time.time()
con = connect("04")


def features(labels: str, cutoff: str) -> pd.DataFrame:
    """One row per labelled user, built only from data on or before `cutoff`."""
    c = f"DATE '{cutoff}'"
    return con.execute(f"""
    WITH lab AS (SELECT msno, is_churn FROM '{parquet(labels)}'),
    tx AS (
        SELECT t.* FROM '{parquet('transactions')}' t JOIN lab USING (msno)
        WHERE t.transaction_date <= {c}
    ),
    tx_agg AS (
        SELECT msno,
            {c} - min(transaction_date) AS tenure_days,
            count(*) AS n_transactions,
            count(*) FILTER (WHERE is_cancel) AS n_cancels,
            count(DISTINCT payment_method_id) AS n_payment_methods,
            avg(is_auto_renew::INT) AS auto_renew_share,
            sum(actual_amount_paid) AS total_paid,
            arg_max(payment_method_id, (transaction_date, membership_expire_date)) AS last_payment_method,
            arg_max(payment_plan_days, (transaction_date, membership_expire_date)) AS last_plan_days,
            arg_max(actual_amount_paid, (transaction_date, membership_expire_date)) AS last_paid,
            arg_max(plan_list_price, (transaction_date, membership_expire_date)) AS last_list_price,
            arg_max(is_auto_renew::INT, (transaction_date, membership_expire_date)) AS last_is_auto_renew,
            arg_max(is_cancel::INT, (transaction_date, membership_expire_date)) AS last_is_cancel,
            arg_max(membership_expire_date, (transaction_date, membership_expire_date)) - {c} AS days_to_expire
        FROM tx GROUP BY msno
    ),
    logs AS (
        SELECT l.msno, l.date, least(greatest(l.total_secs, 0), 86400) AS secs,
               l.num_unq, l.num_25, l.num_100,
               l.num_25 + l.num_50 + l.num_75 + l.num_985 + l.num_100 AS plays
        FROM '{parquet('user_logs')}' l JOIN lab USING (msno)
        WHERE l.date > {c} - INTERVAL 60 DAY AND l.date <= {c}
    ),
    log_agg AS (
        SELECT msno,
            count(DISTINCT date) FILTER (WHERE date > {c} - INTERVAL 30 DAY) AS active_days_30,
            sum(secs) FILTER (WHERE date > {c} - INTERVAL 30 DAY) AS secs_30,
            sum(secs) FILTER (WHERE date <= {c} - INTERVAL 30 DAY) AS secs_prev_30,
            sum(num_unq) FILTER (WHERE date > {c} - INTERVAL 30 DAY) AS unq_30,
            sum(num_100) FILTER (WHERE date > {c} - INTERVAL 30 DAY)
              / nullif(sum(plays) FILTER (WHERE date > {c} - INTERVAL 30 DAY), 0) AS complete_share_30,
            sum(num_25) FILTER (WHERE date > {c} - INTERVAL 30 DAY)
              / nullif(sum(plays) FILTER (WHERE date > {c} - INTERVAL 30 DAY), 0) AS skip_share_30,
            {c} - max(date) AS days_since_last_listen
        FROM logs GROUP BY msno
    )
    SELECT lab.msno, lab.is_churn::INT AS is_churn,
        tx_agg.* EXCLUDE (msno),
        (tx_agg.last_paid = 0)::INT AS last_is_free,
        (tx_agg.last_paid < tx_agg.last_list_price)::INT AS last_is_discounted,
        CASE WHEN m.bd BETWEEN 10 AND 80 THEN m.bd END AS age,
        {c} - m.registration_date AS registration_days,
        m.registered_via, m.city, m.gender,
        coalesce(log_agg.active_days_30, 0) AS active_days_30,
        coalesce(log_agg.secs_30, 0) AS secs_30,
        coalesce(log_agg.unq_30, 0) AS unq_30,
        log_agg.complete_share_30, log_agg.skip_share_30,
        (coalesce(log_agg.secs_30, 0) + 1) / (coalesce(log_agg.secs_prev_30, 0) + 1) AS secs_trend,
        coalesce(log_agg.days_since_last_listen, 60) AS days_since_last_listen
    FROM lab
    LEFT JOIN tx_agg USING (msno)
    LEFT JOIN '{parquet('members')}' m USING (msno)
    LEFT JOIN log_agg USING (msno)
    """).df()


data = {}
for split, (labels, cutoff) in SPLITS.items():
    # Feature extraction scans 410M log rows (~8 min per split); cache it.
    cache = PARQUET_DIR / f"features_{split}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
    else:
        df = features(labels, cutoff)
        df.to_parquet(cache, index=False)
    for col in CATEGORICAL:
        df[col] = df[col].astype("string").fillna("unknown")
    # nullable Int/Float -> float64 so missing values are plain NaN
    df[NUMERIC] = df[NUMERIC].astype("float64")
    data[split] = df
    print(f"  {split}: {len(df):,} users, churn {df.is_churn.mean():.1%} ({time.time() - t0:.0f}s)")
train, test = data["train"], data["test"]

# --- churn rate by segment (test population, i.e. Mar 2017 expiries) --------
def bucket(s, edges, labels):
    return pd.cut(s, edges, labels=labels, right=False).astype("string").fillna("no data")


seg = test.assign(
    renewal=np.where(test.last_is_auto_renew == 1, "auto-renew", "manual"),
    last_action=np.where(test.last_is_cancel == 1, "cancelled", "renewed / paid"),
    plan=bucket(test.last_plan_days, [0, 28, 32, 200, 10_000], ["< 28 days", "monthly", "multi-month", "annual"]),
    price=np.where(test.last_is_free == 1, "free", np.where(test.last_is_discounted == 1, "discounted", "full price")),
    tenure=bucket(test.tenure_days / 30, [0, 3, 6, 12, 24, 1000], ["< 3 mo", "3-6 mo", "6-12 mo", "1-2 yr", "2+ yr"]),
    listening=bucket(test.active_days_30, [0, 1, 5, 15, 31], ["0 days", "1-4 days", "5-14 days", "15-30 days"]),
    listening_trend=bucket(test.secs_trend, [0, 0.5, 0.9, 1.1, 2, np.inf],
                           ["dropped > 50%", "dropped 10-50%", "stable", "up 10-100%", "up > 100%"]),
)
dims = ["renewal", "last_action", "plan", "price", "tenure", "listening", "listening_trend", "registered_via"]
segments = pd.concat([
    seg.groupby(d).is_churn.agg(users="size", churn_rate="mean").reset_index()
       .rename(columns={d: "segment"}).assign(dimension=d)
    for d in dims
])
segments = segments[segments.users >= 1000][["dimension", "segment", "users", "churn_rate"]]
segments["churn_rate"] = segments.churn_rate.round(4)
segments.to_csv(OUTPUT / "churn_driver_segments.csv", index=False)
print(f"  churn_driver_segments.csv: {len(segments)} rows")

# --- models -------------------------------------------------------------------
X_train, y_train = train[CATEGORICAL + NUMERIC], train.is_churn
X_test, y_test = test[CATEGORICAL + NUMERIC], test.is_churn

logit = make_pipeline(
    ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=1000), CATEGORICAL),
        ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), NUMERIC),
    ]),
    LogisticRegression(max_iter=2000, C=1.0),
)
gbm = HistGradientBoostingClassifier(
    categorical_features="from_dtype", max_iter=400, learning_rate=0.08,
    max_leaf_nodes=63, l2_regularization=1.0, early_stopping=True,
    validation_fraction=0.1, random_state=SEED,
)
X_train_gbm = X_train.astype({c: "category" for c in CATEGORICAL})
X_test_gbm = X_test.astype({c: "category" for c in CATEGORICAL})
for c in CATEGORICAL:  # align category sets between train and test
    cats = X_train_gbm[c].cat.categories
    # categories unseen in training become missing
    X_test_gbm[c] = pd.Categorical(X_test_gbm[c].where(X_test_gbm[c].isin(cats)), categories=cats)

models = {
    "logistic_regression": (logit, X_train, X_test),
    "gradient_boosting": (gbm, X_train_gbm, X_test_gbm),
}
rows, scores = [], {}
for name, (model, xtr, xte) in models.items():
    model.fit(xtr, y_train)
    p = model.predict_proba(xte)[:, 1]
    scores[name] = p
    top = p >= np.quantile(p, 0.9)
    rows.append({
        "model": name,
        "roc_auc": round(roc_auc_score(y_test, p), 4),
        "pr_auc": round(average_precision_score(y_test, p), 4),
        "log_loss": round(log_loss(y_test, p), 4),
        "base_churn_rate": round(y_test.mean(), 4),
        "top_decile_churn_rate": round(y_test[top].mean(), 4),
        "top_decile_lift": round(y_test[top].mean() / y_test.mean(), 2),
        "top_decile_share_of_churners": round(y_test[top].sum() / y_test.sum(), 4),
    })
    print(f"  {name}: AUC {rows[-1]['roc_auc']}, PR-AUC {rows[-1]['pr_auc']} ({time.time() - t0:.0f}s)")
pd.DataFrame(rows).to_csv(OUTPUT / "churn_model_metrics.csv", index=False)

# --- risk deciles (best model) -------------------------------------------------
p = scores["gradient_boosting"]
deciles = (
    pd.DataFrame({"score": p, "is_churn": y_test.values})
    .assign(risk_decile=lambda d: 10 - pd.qcut(d.score, 10, labels=False))
    .groupby("risk_decile")
    .agg(users=("score", "size"), avg_predicted=("score", "mean"), actual_churn_rate=("is_churn", "mean"),
         churners=("is_churn", "sum"))
    .reset_index()
)
deciles["share_of_all_churners"] = deciles.churners / deciles.churners.sum()
deciles.round(4).to_csv(OUTPUT / "churn_risk_deciles.csv", index=False)

# --- what drives the model ------------------------------------------------------
rng = np.random.default_rng(SEED)
idx = rng.choice(len(X_test_gbm), size=min(100_000, len(X_test_gbm)), replace=False)
imp = permutation_importance(gbm, X_test_gbm.iloc[idx], y_test.iloc[idx], scoring="roc_auc",
                             n_repeats=3, random_state=SEED, n_jobs=1)
importance = (
    pd.DataFrame({"feature": X_test_gbm.columns, "auc_drop": imp.importances_mean, "std": imp.importances_std})
    .sort_values("auc_drop", ascending=False).round(5)
)
importance.to_csv(OUTPUT / "churn_feature_importance.csv", index=False)
print(importance.head(10).to_string(index=False))
print(f"done in {time.time() - t0:.0f}s")
