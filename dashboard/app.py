"""
Step 5 — Dashboard.

Streamlit app over the Step 3 and Step 4 outputs (small CSVs in output/ —
it never touches the raw data):
  Growth            - KPIs, MRR trend, MRR bridge
  Retention         - paid churn with/without billing gaps, churn reasons,
                      NRR, cohort heatmap, trial conversion
  Churn drivers     - churn by segment, LTV by segment, risk model

Run with:  streamlit run dashboard/app.py
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------
# Palette (validated categorical / sequential / status colors)
# ----------------------------------------------------------------------
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"

CAT = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "violet": "#6250d6",
    "red": "#e34948",
}
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"]

# Fixed movement -> color mapping, reused on every chart.
BRIDGE = [
    ("new_mrr", "New", CAT["blue"]),
    ("reactivation_mrr", "Reactivation", CAT["aqua"]),
    ("expansion_mrr", "Expansion", CAT["violet"]),
    ("contraction_mrr", "Contraction", CAT["yellow"]),
    ("churn_other_mrr", "Churn", CAT["red"]),
    ("churn_billing_gap_mrr", "Churn — billing gap", CAT["orange"]),
]
CHURN_TYPE_COLOR = {
    "manual plan not renewed": CAT["blue"],
    "auto-renew lapsed": CAT["violet"],
    "billing gap": CAT["orange"],
    "cancelled by user": CAT["red"],
}

FONT = dict(family="Segoe UI, system-ui, -apple-system, sans-serif", color=INK, size=13)

st.set_page_config(page_title="KKBox — Subscription Analytics", layout="wide")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"


@st.cache_data
def load(name, date_cols=None):
    return pd.read_csv(OUTPUT / name, parse_dates=date_cols or [])


def style(fig, y_title="", x_title="", legend=True, height=380):
    fig.update_layout(
        template="plotly_white",
        font=FONT,
        height=height,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(color=INK_SECONDARY, size=12),
        ) if legend else None,
        showlegend=legend,
        hoverlabel=dict(bgcolor=SURFACE, font=FONT, bordercolor=BASELINE),
    )
    fig.update_xaxes(
        title=dict(text=x_title, font=dict(color=INK_MUTED, size=12)),
        showgrid=False, linecolor=BASELINE, tickfont=dict(color=INK_MUTED),
    )
    fig.update_yaxes(
        title=dict(text=y_title, font=dict(color=INK_MUTED, size=12)),
        showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=BASELINE,
        tickfont=dict(color=INK_MUTED),
    )
    return fig


def hbar(df, x, y, fmt, color=CAT["blue"], x_title=""):
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y], orientation="h", marker_color=color,
        text=[fmt(v) for v in df[x]], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br>%{x}<extra></extra>",
    ))
    fig = style(fig, x_title=x_title, legend=False, height=max(220, 42 * len(df)))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, range=[0, df[x].max() * 1.3])
    fig.update_yaxes(showgrid=False)
    return fig


waterfall = load("mrr_waterfall.csv", ["month"]).fillna(0)
churn = load("churn_rate_by_month.csv", ["month"])
summary = load("monthly_summary.csv", ["month"])

st.title("KKBox — Subscription Analytics")
st.caption(
    "Taiwan music-streaming subscriptions · Kaggle KKBox churn data · "
    "all money in NTD · report window Jul 2015 – Feb 2017"
)

# Report-window filter, applied to every time series on the page.
months = waterfall.month.dt.to_period("M").astype(str).tolist()
start, end = st.select_slider("Months shown", options=months, value=(months[0], months[-1]))
in_window = lambda d: d[(d.month >= pd.Timestamp(start)) & (d.month <= pd.Timestamp(end))]  # noqa: E731
wf, ch = in_window(waterfall), in_window(churn)

tab_growth, tab_retention, tab_drivers = st.tabs(["Growth", "Retention", "Churn drivers & model"])

# ========================================================================
# TAB 1 — Growth
# ========================================================================
with tab_growth:
    first, last = wf.iloc[0], wf.iloc[-1]
    paying = summary.set_index("month").paying_users
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"MRR ({last.month:%b %Y})", f"{last.ending_mrr / 1e6:,.1f}M NTD",
              f"{last.ending_mrr / last.starting_mrr - 1:+.1%} MoM")
    c2.metric("MRR growth in window", f"{last.ending_mrr / first.ending_mrr - 1:+.1%}")
    c3.metric("Paying users", f"{paying.get(last.month, float('nan')):,.0f}")
    c4.metric("Avg. monthly NRR", f"{ch.nrr.mean():.1%}", "below 100%" if ch.nrr.mean() < 1 else None,
              delta_color="inverse")

    st.subheader("MRR over time")
    fig = go.Figure(go.Scatter(
        x=wf.month, y=wf.ending_mrr, mode="lines", line=dict(color=CAT["blue"], width=2.5),
        fill="tozeroy", fillcolor="rgba(42,120,214,0.10)", name="MRR",
        hovertemplate="%{x|%b %Y}<br>%{y:,.0f} NTD<extra></extra>",
    ))
    st.plotly_chart(style(fig, y_title="MRR (NTD)", legend=False), width="stretch")

    st.subheader("Where MRR moves each month")
    fig = go.Figure()
    for col, label, color in BRIDGE:
        fig.add_bar(x=wf.month, y=wf[col], name=label, marker_color=color,
                    hovertemplate="%{x|%b %Y}<br>" + label + ": %{y:,.0f} NTD<extra></extra>")
    fig.add_scatter(x=wf.month, y=wf.ending_mrr - wf.starting_mrr, name="Net change",
                    mode="lines+markers", line=dict(color=INK, width=1.5), marker=dict(size=5),
                    hovertemplate="%{x|%b %Y}<br>Net: %{y:,.0f} NTD<extra></extra>")
    fig.update_layout(barmode="relative")
    st.plotly_chart(style(fig, y_title="MRR movement (NTD)", height=420), width="stretch")

    totals = wf[[c for c, _, _ in BRIDGE]].sum()
    st.caption(
        f"In the selected window, new users added {totals.new_mrr / 1e6:,.1f}M NTD of MRR and "
        f"returning users {totals.reactivation_mrr / 1e6:,.1f}M; churn removed "
        f"{-(totals.churn_other_mrr + totals.churn_billing_gap_mrr) / 1e6:,.1f}M, of which "
        f"{-totals.churn_billing_gap_mrr / 1e6:,.1f}M came from payment-partner outages."
    )

# ========================================================================
# TAB 2 — Retention
# ========================================================================
with tab_retention:
    cohort = load("cohort_retention.csv", ["cohort"])
    trials = in_window(load("trial_conversion.csv", ["month"]))
    types = load("churn_type_by_month.csv", ["month"])
    types = types[(types.month >= pd.Timestamp(start)) & (types.month <= pd.Timestamp(end))]
    episodes = load("billing_gap_episodes.csv", ["month"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg. paid churn / mo", f"{ch.paid_churn.mean():.1%}")
    c2.metric("…excl. billing gaps", f"{ch.paid_churn_ex_gap.mean():.1%}")
    c3.metric("Avg. revenue churn / mo", f"{ch.revenue_churn.mean():.1%}")
    c4.metric("Trial → paid conversion",
              f"{trials.converted.sum() / max(trials.trial_starts.sum(), 1):.1%}")

    st.subheader("Paid churn, with and without payment-partner outages")
    fig = go.Figure()
    fig.add_scatter(x=ch.month, y=ch.paid_churn, name="Paid churn (Kaggle rule)", mode="lines+markers",
                    line=dict(color=CAT["orange"], width=2.5), marker=dict(size=6),
                    customdata=ch.billing_gap_users,
                    hovertemplate="%{x|%b %Y}<br>Paid churn: %{y:.1%}<br>"
                                  "Billing-gap users: %{customdata:,}<extra></extra>")
    fig.add_scatter(x=ch.month, y=ch.paid_churn_ex_gap, name="Excl. billing gaps", mode="lines+markers",
                    line=dict(color=CAT["blue"], width=2.5), marker=dict(size=6),
                    hovertemplate="%{x|%b %Y}<br>Excl. gaps: %{y:.1%}<extra></extra>")
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    st.plotly_chart(style(fig, y_title="Monthly paid churn"), width="stretch")
    with st.expander(f"Detected billing-gap outages ({len(episodes)})"):
        st.dataframe(
            episodes.assign(month=episodes.month.dt.strftime("%b %Y")).rename(columns={
                "payment_method_id": "Payment method", "month": "Month", "churned": "Paid churners",
                "usual_churn": "Usual churn", "multiple": "× usual", "return_share": "Returned ≤ 6 mo",
            }),
            hide_index=True, width="stretch",
            column_config={"Returned ≤ 6 mo": st.column_config.NumberColumn(format="percent")},
        )

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Why paying users leave")
        t = types.groupby("churn_type").users.sum().sort_values()
        share = (t / t.sum()).reset_index(name="share")
        fig = hbar(share, "share", "churn_type", lambda v: f"{v:.0%}",
                   color=[CHURN_TYPE_COLOR[c] for c in share.churn_type])
        fig.update_xaxes(tickformat=".0%")
        st.plotly_chart(fig, width="stretch")
    with col_b:
        st.subheader("Net revenue retention")
        fig = go.Figure(go.Scatter(
            x=ch.month, y=ch.nrr, mode="lines+markers", line=dict(color=CAT["blue"], width=2.5),
            marker=dict(size=6), hovertemplate="%{x|%b %Y}<br>NRR: %{y:.1%}<extra></extra>",
        ))
        fig.add_hline(y=1.0, line_dash="dash", line_color=BASELINE, annotation_text="100%",
                      annotation_font=dict(color=INK_MUTED))
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(style(fig, y_title="NRR", legend=False, height=260), width="stretch")

    st.subheader("Cohort retention — % of first-payment cohort still paying")
    pivot = cohort.pivot(index="cohort", columns="months_since_start", values="retention")
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=pivot.columns, y=pivot.index.strftime("%b %Y"),
        colorscale=[[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(SEQ_BLUE)],
        zmin=0.6, zmax=1, colorbar=dict(title="Retention", tickformat=".0%"),
        hovertemplate="Cohort %{y}<br>Month +%{x}: %{z:.0%}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(style(fig, y_title="First-payment cohort", x_title="Months since first payment",
                          legend=False, height=520), width="stretch")
    st.caption("Colour scale starts at 60%. Cells can rise over time when users come back (reactivation).")

# ========================================================================
# TAB 3 — Churn drivers & model
# ========================================================================
with tab_drivers:
    seg = load("churn_driver_segments.csv")
    ltv = load("ltv_by_segment.csv")
    metrics = load("churn_model_metrics.csv").set_index("model")
    deciles = load("churn_risk_deciles.csv")
    imp = load("churn_feature_importance.csv")

    gb = metrics.loc["gradient_boosting"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Model ROC AUC (out-of-time)", f"{gb.roc_auc:.3f}",
              f"{gb.roc_auc - metrics.loc['logistic_regression'].roc_auc:+.3f} vs logistic")
    c2.metric("Base churn rate (Mar 2017)", f"{gb.base_churn_rate:.1%}")
    c3.metric("Churn in top-10% risk", f"{gb.top_decile_churn_rate:.1%}", f"{gb.top_decile_lift:.1f}× lift")
    c4.metric("Churners caught in top 10%", f"{gb.top_decile_share_of_churners:.0%}")

    labels = {"renewal": "Renewal type", "last_action": "Last action", "plan": "Plan length",
              "price": "Price paid", "tenure": "Tenure", "listening": "Days listened (last 30)",
              "listening_trend": "Listening trend", "registered_via": "Sign-up channel"}
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Churn rate by segment")
        picked = st.selectbox("Segment by", list(labels.values()), key="seg")
        dim = {v: k for k, v in labels.items()}[picked]
        d = seg[seg.dimension == dim].sort_values("churn_rate")
        fig = hbar(d, "churn_rate", "segment", lambda v: f"{v:.0%}",
                   color=[CAT["red"] if v > 2 * gb.base_churn_rate else CAT["blue"] for v in d.churn_rate])
        fig.add_vline(x=gb.base_churn_rate, line_dash="dash", line_color=INK_MUTED,
                      annotation_text="average", annotation_font=dict(color=INK_MUTED))
        fig.update_xaxes(tickformat=".0%")
        st.plotly_chart(fig, width="stretch")
        st.caption("Users expiring in Mar 2017, by their state at the end of Feb 2017.")
    with col_b:
        st.subheader("Lifetime value by segment")
        ltv_labels = {"renewal": "Renewal type", "plan_length": "Plan length",
                      "registered_via": "Sign-up channel", "payment_method": "Payment method", "city": "City"}
        picked = st.selectbox("Segment by", list(ltv_labels.values()), key="ltv")
        ldim = {v: k for k, v in ltv_labels.items()}[picked]
        d = ltv[ltv.dimension == ldim].sort_values("ltv_ntd").tail(12)
        st.plotly_chart(hbar(d, "ltv_ntd", "segment", lambda v: f"{v:,.0f}", x_title="LTV (NTD)"),
                        width="stretch")
        st.caption("LTV = ARPU ÷ monthly paid churn (billing gaps excluded). Top 12 segments shown.")

    col_c, col_d = st.columns(2)
    with col_c:
        st.subheader("Actual churn by predicted risk decile")
        fig = go.Figure(go.Bar(
            x=deciles.risk_decile.astype(str), y=deciles.actual_churn_rate,
            marker_color=[CAT["red"] if d == 1 else CAT["blue"] for d in deciles.risk_decile],
            customdata=deciles.share_of_all_churners,
            text=[f"{v:.0%}" for v in deciles.actual_churn_rate], textposition="outside",
            hovertemplate="Decile %{x}<br>Churn %{y:.1%}<br>%{customdata:.0%} of all churners<extra></extra>",
        ))
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(style(fig, y_title="Actual churn", x_title="Risk decile (1 = highest)",
                              legend=False), width="stretch")
    with col_d:
        st.subheader("What drives the model")
        d = imp.head(10).sort_values("auc_drop")
        st.plotly_chart(hbar(d, "auc_drop", "feature", lambda v: f"{v:.3f}",
                             x_title="ROC AUC lost when the feature is shuffled"),
                        width="stretch")

    st.caption(
        "Gradient boosting trained on Feb 2017 expiries (data to 31 Jan) and tested on Mar 2017 "
        "expiries (data to 28 Feb) — the same one-month-ahead view the business would have."
    )
