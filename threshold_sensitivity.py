"""
threshold_sensitivity.py — False positive rate analysis across the 213-ticker universe.

Models each ticker's normal-day volume as lognormal (fit from median + MAD),
then estimates the probability of exceeding each signal threshold on a random
normal trading day.

Key output: expected false alerts per day at each tier.

Decision logic:
  - S4 false positives > 5/day: too much noise; raise VOL_SUSTAINED.
  - S3 false positives > 2/day: review VOL_CONFIRMED.
  - S2 false positives > 0.5/day: serious miscalibration; check baseline window.
  - S1 false positives (zero-volume ARA): should be 0 on normal days.
"""

import json
import math
import sys

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_DIR       = "C:/Users/zhang/Desktop/BGC/data"
BASELINE_FILE  = f"{DATA_DIR}/processed/baselines_aug_sep_2026_clean.json"

# ── Signal thresholds (must match production_monitor.py) ─────────────────────
THRESHOLDS = {
    "S2_early":  15.0,
    "S2_normal":  8.0,
    "S3":         4.0,
    "S4":         2.5,
    "S5":         2.0,
}

# False-positive budget: max expected alerts per day before we call it noise
FP_BUDGET = {
    "S2_early":  0.1,
    "S2_normal": 0.5,
    "S3":        1.0,
    "S4":        5.0,
    "S5":       10.0,
}


def lognormal_exceedance(median, mad, threshold_ratio):
    """
    P(X > threshold_ratio * median) where X ~ LogNormal fit to (median, MAD).

    LogNormal median = exp(mu)  => mu = log(median)
    MAD of lognormal ≈ median * (exp(sigma) - 1) * 0.6745  (approximation)
    => sigma ≈ log(1 + MAD / (0.6745 * median))
    """
    if median <= 0 or mad < 0:
        return 0.0
    if threshold_ratio <= 0:
        return 1.0

    mu    = math.log(median)
    ratio = mad / (0.6745 * median)
    if ratio <= 0:
        sigma = 1e-9
    else:
        sigma = math.log(1 + ratio)

    # P(X > k * median) = P(Z > (log(k) + mu - mu) / sigma) = P(Z > log(k)/sigma)
    z = math.log(threshold_ratio) / sigma if sigma > 1e-9 else float("inf")
    return _normal_sf(z)


def _normal_sf(z):
    """Survival function of standard normal via math.erfc."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def main():
    with open(BASELINE_FILE, encoding="utf-8") as f:
        baselines = json.load(f)

    n = len(baselines)
    print("=" * 65)
    print(f"THRESHOLD SENSITIVITY ANALYSIS  ({n} tickers)")
    print("=" * 65)

    # Per-threshold: sum of per-ticker exceedance probabilities = expected FP/day
    expected_fp = {k: 0.0 for k in THRESHOLDS}
    high_sensitivity = {k: [] for k in THRESHOLDS}  # tickers easiest to false-trigger

    for ticker, data in baselines.items():
        st     = data.get("short_term", {})
        median = st.get("median_volume", 0)
        mad    = st.get("mad", 0)

        if not median or median <= 0:
            continue

        for label, mult in THRESHOLDS.items():
            p = lognormal_exceedance(median, mad, mult)
            expected_fp[label] += p
            if p > 0.05:   # > 5% chance on any normal day: flag for review
                high_sensitivity[label].append((ticker, round(p * 100, 1)))

    # ── Results table ─────────────────────────────────────────────────────
    print(f"\n  {'Threshold':<14} {'Multiplier':>10} {'E[FP/day]':>10} "
          f"{'Budget':>8}  {'Status':<8}")
    print("  " + "-" * 55)

    failures = 0
    for label, mult in THRESHOLDS.items():
        fp    = expected_fp[label]
        budg  = FP_BUDGET[label]
        ok    = fp <= budg
        tag   = "[PASS]" if ok else "[FAIL]"
        if not ok:
            failures += 1
        print(f"  {label:<14} {mult:>9.1f}x {fp:>10.2f} {budg:>8.1f}  {tag}")

    # ── High-sensitivity tickers ──────────────────────────────────────────
    print()
    for label in ["S4", "S3"]:
        tickers = sorted(high_sensitivity[label], key=lambda x: -x[1])[:8]
        if tickers:
            names = ", ".join(f"{t}({p}%)" for t, p in tickers)
            print(f"  Highest S4 false-positive risk: {names}")
            print(f"  (These tickers have volatile normal-day volume; expect occasional noise.)")
            break

    # ── S3/S4 overlap: tickers that are borderline ────────────────────────
    borderline = []
    for ticker, data in baselines.items():
        st     = data.get("short_term", {})
        median = st.get("median_volume", 0)
        mad    = st.get("mad", 0)
        if not median or median <= 0:
            continue
        p_s3 = lognormal_exceedance(median, mad, THRESHOLDS["S3"])
        if 0.01 < p_s3 < 0.10:
            borderline.append((ticker, round(p_s3 * 100, 1)))

    borderline.sort(key=lambda x: -x[1])
    if borderline:
        print(f"\n  S3 borderline tickers (1-10% daily FP chance): "
              f"{len(borderline)} tickers")
        print(f"  Top 5: {', '.join(t for t, _ in borderline[:5])}")
        print(f"  When one of these fires S3, check if it also fired S2 first — "
              f"co-confirmation is a stronger signal.")

    # ── Summary verdict ───────────────────────────────────────────────────
    print()
    print("=" * 65)
    if failures == 0:
        print("RESULT: THRESHOLDS WELL-CALIBRATED — false positive rates within budget")
    else:
        print(f"RESULT: {failures} THRESHOLD(S) EXCEED BUDGET — review before competition")
        for label, mult in THRESHOLDS.items():
            if expected_fp[label] > FP_BUDGET[label]:
                print(f"  {label}: E[FP]={expected_fp[label]:.1f}/day, "
                      f"consider raising threshold from {mult}x")
    print("=" * 65)

    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
