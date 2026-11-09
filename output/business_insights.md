# KKBox subscription analytics — business insights

**Period:** Jul 2015 – Feb 2017 (metrics) · Mar 2017 expiries (churn model) · all money in NTD
**Sources:** every number below is reproduced by `scripts/01`–`04` and lives in [`output/`](.).

## Summary

KKBox grows revenue (+44.5% MRR in 20 months) but loses about 5% of its
existing revenue every month, so growth depends on constantly adding and
winning back users. Most churn is not users deciding to leave: it happens in
the **billing flow** — manual plans that are never renewed, auto-renew payments
that fail, and payment-partner outages. Only 6% of paid churn is an explicit
cancellation. **Fixing billing is the highest-value retention lever**, and a
churn model that ranks users one month ahead can focus the effort.

| Question | Answer |
|---|---|
| 1. Is growth healthy? | Partly. MRR +44.5%, but NRR averages 94.8%/month and growth leans on win-backs. |
| 2. Which segments are worth most? | Auto-renew (3.6× the LTV of manual payers), annual plans (2.4× monthly) and sign-up channel 7 (4.5× channel 4). |
| 3. Where to act first? | Billing: move manual payers to auto-renew, recover failed renewals, monitor payment partners. Not voluntary cancellations, not low listeners. |

---

## 1. Is growth healthy?

### Finding
- MRR grew from **104.5M to 151.1M NTD** (+44.5%); paying users reached **1.17M** in Feb 2017.
- **NRR averaged 94.8% a month**: users paying last month bring ~5% less revenue this month.
- Over 20 months, MRR movements were: new **+118.8M**, reactivation **+63.7M**,
  expansion **+5.0M**, contraction **−11.3M**, churn **−107.1M**, billing-gap churn **−18.6M**.
- Paid churn averaged **4.6%/month**, **3.9%** once billing gaps are excluded.
- **Trial conversion is low: 13.1%** (45,452 of 346,605 trial starts paid within 3 months).

### So what
- Expansion is structurally absent (one main price point), so the existing base can only shrink;
  retention is the only lever on it.
- **Win-backs are a hidden growth engine** — reactivations added more than half as much MRR
  as new users. Many "churned" users are not lost for good.
- Growth is not fragile today, but it is expensive: every month ~4% of paying users must be replaced.

### Recommendation
- Report **NRR and paid churn excl. billing gaps** as the headline retention KPIs, next to MRR.
- Treat reactivation as a channel: track win-back rate and target lapsed users within 6 months.
- Investigate the trial funnel: 87% of trial users never pay.

---

## 2. Which segments are worth most?

### Finding
LTV = ARPU ÷ monthly paid churn (billing gaps excluded). ARPU is nearly flat
(~120–150 NTD), so **LTV is decided by churn**.

| Segment | LTV (NTD) | Monthly churn |
|---|---:|---:|
| Auto-renew | 5,874 | 2.2% |
| Manual renewal | 1,620 | 8.5% |
| Annual plan (> 200 days) | 7,850 | 1.6% |
| Monthly plan (≤ 31 days) | 3,286 | 4.1% |
| Sign-up channel 7 | 6,584 | 1.9% |
| Sign-up channel 4 | 1,467 | 10.2% |

- Payment method 38 carries 2.26M paying user-months but churns at **10.9%/month** (LTV 1,302 NTD),
  vs 2.1% for the dominant method 41 (LTV 5,903 NTD).
- Cohorts lose **~12% after the first month** and ~22% by month 6, then flatten:
  **69–75% of a cohort is still paying after 12 months**.

### So what
- Users who reach month 3 are very sticky; the **first 1–3 months** are where retention is won or lost.
- Acquisition through channel 4 and payment method 38 brings users worth less than a third of the best segments.

### Recommendation
- Weight acquisition budget toward channel 7 and the payment methods with low churn.
- Offer annual plans (e.g. a discount equal to one or two months) — even with a discount,
  annual LTV stays well above monthly.
- Build an onboarding programme for the first 90 days of a paid subscription.

---

## 3. Where should KKBox act first?

### Finding
**Why paying users leave** (867,786 paid churn events):

| Reason | Share |
|---|---:|
| Manual plan not renewed | 49% |
| Auto-renew payment lapsed | 30% |
| Billing gap (payment-partner outage) | 15% |
| Cancelled by user | 6% |

**Payment-partner outages.** The pipeline detected 7 mass outages (a method's
churn ≥ 3× normal, ≥ 5,000 users, most returning on the same method). The
largest — **method 39, Mar 2016** — cut off **71,108 paying users** (61× its
normal churn); **97.5% came back**, but 18.6M NTD of MRR was lost across all
outages while users were away.

**What predicts churn one month ahead** (users expiring Mar 2017):

| State one month earlier | Churn rate |
|---|---:|
| Manual renewal | 42% |
| Auto-renew | 5% |
| Last action was a cancel | 84% |
| Tenure < 3 months | 13% |
| Tenure 2+ years | 8% |
| No listening in last 30 days | 7% |
| Listened 15–30 days | 9% |

Users who stopped listening churn *less* overall because 98.5% of them are on
auto-renew and keep paying; within auto-renew, silent users churn at 5.7% vs 3.8%
for active ones.

**Churn model.** Gradient boosting trained on Feb 2017 expiries and tested on
Mar 2017 expiries (out-of-time, no leakage) reaches **ROC AUC 0.871**
(logistic baseline 0.825). The top 10% riskiest users churn at **54%** (6.0×
the average) and hold **60% of all churners**. Renewal type is by far the
strongest driver, followed by a recent cancel, price, days to expiry, payment
method and tenure.

### So what
- **Churn is a billing problem before it is a product problem.** 79% of paid churn is a renewal
  that did not happen (manual or failed auto-renew); explicit cancellation is only 6%.
- Payment-partner outages are an **operational risk outside the product team's control** —
  churn-reduction campaigns cannot fix them, and the Kaggle churn definition counts them as churn.
- Re-engaging low listeners is the wrong first target: they are mostly still paying.
  They are revenue at risk later, not churn now.

### Recommendation (in priority order)

1. **Convert manual payers to auto-renew.** Manual users churn at 42% vs 5% before expiry.
   Prompt auto-renew at checkout and at each manual renewal, with an incentive.
   Run it as an A/B test: part of the LTV gap (1,620 → 5,874 NTD) is self-selection,
   so the true uplift must be measured, not assumed.
2. **Recover failed auto-renew payments** (30% of paid churn): retry schedules, card-update
   reminders before expiry, a grace-period notice.
3. **Monitor payment partners.** Alert when any method's daily failed renewals exceed 3× its
   normal level; agree SLAs with partners; prompt affected users to switch method. Report churn
   with and without billing gaps so outages do not hide the underlying trend.
4. **Use the risk model monthly.** Score users one month before expiry; send the top decile
   (~97k users, 60% of next month's churners) to retention offers, and trigger a save offer
   immediately on any cancel (84% churn).
5. **Fix early life.** Onboarding for the first 90 days, and a review of the trial funnel (13% conversion).

---

## Limitations

- **No acquisition cost data:** CAC and LTV:CAC cannot be computed; segments are compared on LTV only.
- **Correlation, not causation:** segment and model results show who churns, not what would change it.
  Recommendations 1 and 4 should be validated with experiments.
- **Left-censored start:** no data before Jan 2015, so metrics start in Jul 2015 after a 6-month warm-up.
- **Anonymised IDs:** payment methods, cities and sign-up channels are numeric codes, so outages and
  segments can be located but not named.
- **Sparse member data:** age is invalid for 67% of members, gender missing for 65%, and 18% of paying
  users have no member record.
- **One price point:** expansion is near zero, so NRR here mostly measures churn.
