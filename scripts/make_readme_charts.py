"""
Render the static charts embedded in README.md from the metric CSVs.

Run after 03_calculate_metrics.py:  python scripts/make_readme_charts.py
Output: docs/images/*.png
"""

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

from config import OUTPUT, ROOT

IMG = ROOT / "docs" / "images"

# Reference palette (dataviz skill, light mode)
SURFACE = "#fcfcfb"
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 10.5,
    "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "xtick.major.size": 0, "ytick.major.size": 0, "legend.frameon": False,
})

millions = FuncFormatter(lambda v, _: f"{v / 1e6:,.0f}M")


def finish(fig, ax, title, subtitle, name):
    ax.set_title(title, loc="left", fontsize=14, fontweight="bold", pad=26)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=INK_2, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(IMG / f"{name}.png", dpi=160)
    plt.close(fig)
    print(f"  docs/images/{name}.png")


def month_axis(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))


def mrr_trend():
    wf = pd.read_csv(OUTPUT / "mrr_waterfall.csv", parse_dates=["month"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(wf.month, wf.ending_mrr, color=BLUE, lw=2.2)
    ax.fill_between(wf.month, wf.ending_mrr, color=BLUE, alpha=0.08)
    first, last = wf.iloc[0], wf.iloc[-1]
    for row, ha in ((first, "left"), (last, "right")):
        ax.plot(row.month, row.ending_mrr, "o", ms=8, color=BLUE, mec=SURFACE, mew=2)
        ax.annotate(f"{row.ending_mrr / 1e6:,.1f}M NTD", (row.month, row.ending_mrr),
                    xytext=(0, 12), textcoords="offset points", ha=ha, fontweight="bold")
    ax.yaxis.set_major_formatter(millions)
    ax.set_ylim(0, wf.ending_mrr.max() * 1.2)
    month_axis(ax)
    growth = last.ending_mrr / first.ending_mrr - 1
    finish(fig, ax, "Monthly recurring revenue",
           f"NTD, month-end · +{growth:.0%} from {first.month:%b %Y} to {last.month:%b %Y}", "mrr_trend")


def mrr_bridge():
    wf = pd.read_csv(OUTPUT / "mrr_waterfall.csv", parse_dates=["month"]).fillna(0)
    parts = [("new_mrr", "New", BLUE), ("reactivation_mrr", "Reactivation", AQUA),
             ("expansion_mrr", "Expansion", VIOLET),
             ("contraction_mrr", "Contraction", YELLOW),
             ("churn_other_mrr", "Churn", RED), ("churn_billing_gap_mrr", "Churn — billing gap", ORANGE)]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    pos = neg = 0
    for col, label, color in parts:
        vals = wf[col]
        base = pos if vals.ge(0).all() else neg
        ax.bar(wf.month, vals, width=24, bottom=base, color=color, label=label,
               edgecolor=SURFACE, linewidth=1)
        if vals.ge(0).all():
            pos = pos + vals
        else:
            neg = neg + vals
    net = wf.ending_mrr - wf.starting_mrr
    ax.plot(wf.month, net, color=INK, lw=1.6, marker="o", ms=4, label="Net change")
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.yaxis.set_major_formatter(millions)
    month_axis(ax)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.14), fontsize=9.5)
    finish(fig, ax, "Where MRR moves each month",
           "NTD · gains above zero, losses below · orange = mass payment-partner outages",
           "mrr_bridge")


def churn_rates():
    cr = pd.read_csv(OUTPUT / "churn_rate_by_month.csv", parse_dates=["month"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(cr.month, cr.paid_churn, color=ORANGE, lw=2, label="Paid churn (Kaggle rule)")
    ax.plot(cr.month, cr.paid_churn_ex_gap, color=BLUE, lw=2.2, label="Paid churn excl. billing gaps")
    gaps = cr[cr.billing_gap_users > 0]
    ax.plot(gaps.month, gaps.paid_churn, "o", ms=8, color=ORANGE, mec=SURFACE, mew=2,
            label="Month with a billing-gap outage")
    top = gaps.loc[gaps.billing_gap_users.idxmax()]
    ax.annotate(f"{top.month:%b %Y}: {top.billing_gap_users / 1e3:,.0f}k users cut off\n"
                "by a payment-method outage", (top.month, top.paid_churn),
                xytext=(14, -6), textcoords="offset points", color=INK, fontsize=9.5, va="top")
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_ylim(0, cr.paid_churn.max() * 1.25)
    month_axis(ax)
    ax.legend(loc="upper right")
    finish(fig, ax, "Monthly paid churn",
           "% of paying users at month start who are gone by month end", "churn_rates")


def cohort_heatmap():
    co = pd.read_csv(OUTPUT / "cohort_retention.csv", parse_dates=["cohort"])
    grid = co.pivot(index="cohort", columns="months_since_start", values="retention").iloc[:, :13]
    fig, ax = plt.subplots(figsize=(10, 6))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    im = ax.imshow(grid.values, aspect="auto", cmap=cmap, vmin=0.6, vmax=1)
    ax.set_xticks(range(grid.shape[1]), [str(c) for c in grid.columns])
    ax.set_yticks(range(grid.shape[0]), [f"{d:%b %Y}" for d in grid.index], fontsize=9)
    for (i, j), v in pd.DataFrame(grid.values).stack().items():
        if j in (1, 3, 6, 12) and pd.notna(v):
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=8,
                    color="white" if v > 0.8 else INK)
    ax.grid(False)
    ax.set_xlabel("Months since first payment")
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, format=PercentFormatter(1, decimals=0))
    cbar.outline.set_visible(False)
    finish(fig, ax, "Cohort retention",
           "% of each first-payment cohort still paying N months later · scale starts at 60%", "cohort_retention")


def churn_types():
    ct = pd.read_csv(OUTPUT / "churn_type_by_month.csv")
    tot = ct.groupby("churn_type").users.sum().sort_values()
    share = tot / tot.sum()
    colors = {k: (ORANGE if k == "billing gap" else BLUE) for k in share.index}
    fig, ax = plt.subplots(figsize=(10, 3.4))
    ax.barh(share.index, share.values, color=[colors[k] for k in share.index], height=0.6)
    for i, (k, v) in enumerate(share.items()):
        ax.text(v + 0.005, i, f"{v:.0%}  ({tot[k] / 1e3:,.0f}k users)", va="center", color=INK)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlim(0, share.max() * 1.35)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    finish(fig, ax, "Why paying users leave",
           "Share of all paid churn events in the report window", "churn_types")


def ltv_segments():
    lt = pd.read_csv(OUTPUT / "ltv_by_segment.csv")
    groups = [("plan_length", "By plan length"), ("renewal", "By renewal type")]
    fig, axes = plt.subplots(2, 1, figsize=(10, 4.8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2], "hspace": 0.45})
    xmax = lt[lt.dimension.isin([g for g, _ in groups])].ltv_ntd.max() * 1.5
    for ax, (dim, label) in zip(axes, groups):
        d = lt[lt.dimension == dim].sort_values("ltv_ntd")
        ax.barh(d.segment, d.ltv_ntd, color=BLUE, height=0.6)
        for i, (v, c) in enumerate(zip(d.ltv_ntd, d.monthly_churn)):
            ax.text(v, i, f"  {v:,.0f} NTD · churn {c:.1%}/mo", va="center", color=INK)
        ax.set_xlim(0, xmax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        ax.text(0, 1.04, label, transform=ax.transAxes, color=INK_2, fontweight="bold")
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    fig.text(0.2, 0.955, "Lifetime value by plan type", fontsize=14, fontweight="bold")
    fig.text(0.2, 0.895, "LTV = ARPU ÷ monthly paid churn (billing gaps excluded), NTD",
             color=INK_2, fontsize=10.5)
    fig.subplots_adjust(left=0.2, right=0.97, top=0.78, bottom=0.08)
    fig.savefig(IMG / "ltv_segments.png", dpi=160)
    plt.close(fig)
    print("  docs/images/ltv_segments.png")


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    for chart in (mrr_trend, mrr_bridge, churn_rates, cohort_heatmap, churn_types, ltv_segments):
        chart()
