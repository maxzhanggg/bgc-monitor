"""
verify_baseline_health.py — Validate baseline data quality before competition.

Run this before Oct 13 and after any re-run of calculate_baselines.py.
Each check ends with [PASS], [WARN], or [FAIL] + a concrete action if not PASS.
"""

import json
import sys
from datetime import date

# ── Paths (mirror production_monitor.py) ────────────────────────────────────
DATA_DIR = "C:/Users/zhang/Desktop/BGC/data"
BASELINE_FILE = f"{DATA_DIR}/processed/baselines_aug_sep_2026_clean.json"

# ── Expected constants ───────────────────────────────────────────────────────
EXPECTED_TICKERS    = 213
MIN_DAYS_COUNT      = 20        # fewer days = unreliable median
BASELINE_LAST_DATE  = "2026-09-14"
BASELINE_FIRST_DATE = "2026-08-03"
MAX_MAD_RATIO       = 3.0       # MAD > 3x median signals wild data

# ── Helpers ──────────────────────────────────────────────────────────────────
def result(label, ok, warn=False, action=""):
    tag = "[PASS]" if ok else ("[WARN]" if warn else "[FAIL]")
    line = f"  {tag}  {label}"
    if not ok and action:
        line += f"\n         -> {action}"
    print(line)
    return ok or warn  # True = not a hard failure


def main():
    print("=" * 60)
    print("BASELINE HEALTH CHECK")
    print("=" * 60)

    # ── 1. File exists ───────────────────────────────────────────────────────
    try:
        with open(BASELINE_FILE, encoding="utf-8") as f:
            baselines = json.load(f)
    except FileNotFoundError:
        print(f"  [FAIL]  Baseline file not found: {BASELINE_FILE}")
        print("         -> Run calculate_baselines.py first.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"  [FAIL]  Baseline file is corrupt: {e}")
        print("         -> Delete the file and re-run calculate_baselines.py.")
        sys.exit(1)

    failures = 0

    # ── 2. Ticker count ──────────────────────────────────────────────────────
    count = len(baselines)
    ok = count >= EXPECTED_TICKERS
    if not result(f"Ticker count: {count} (expected >= {EXPECTED_TICKERS})", ok,
                  action="Re-run calculate_baselines.py; check data/snapshots for missing dates."):
        failures += 1

    # ── 3. Per-ticker checks ─────────────────────────────────────────────────
    thin_days, zero_vol, stale_date, bad_mad, zero_price = [], [], [], [], []

    for ticker, data in baselines.items():
        st = data.get("short_term", {})
        ps = data.get("price_stats", {})

        days = data.get("days_count", 0)
        if days < MIN_DAYS_COUNT:
            thin_days.append((ticker, days))

        med_vol = st.get("median_volume", 0)
        if not med_vol or med_vol <= 0:
            zero_vol.append(ticker)

        last = data.get("last_date", "")
        if last != BASELINE_LAST_DATE:
            stale_date.append((ticker, last))

        mad = st.get("mad", 0)
        if med_vol and med_vol > 0 and mad / med_vol > MAX_MAD_RATIO:
            bad_mad.append((ticker, round(mad / med_vol, 2)))

        if ps.get("median_price", 0) <= 0:
            zero_price.append(ticker)

    # days count
    ok = len(thin_days) == 0
    msg = f"Tickers with < {MIN_DAYS_COUNT} days: {len(thin_days)}"
    if thin_days:
        msg += f"  ({', '.join(t for t, _ in thin_days[:5])}{'...' if len(thin_days)>5 else ''})"
    if not result(msg, ok, warn=len(thin_days) <= 5,
                  action="These tickers have sparse data; their signals will be less reliable. "
                         "Acceptable if < 5 tickers. If many, re-pull snapshots for missing dates."):
        failures += 1

    # zero volume
    ok = len(zero_vol) == 0
    msg = f"Tickers with zero median volume: {len(zero_vol)}"
    if zero_vol:
        msg += f"  ({', '.join(zero_vol[:5])}{'...' if len(zero_vol)>5 else ''})"
    if not result(msg, ok,
                  action="These tickers will never trigger any signal. "
                         "Remove them from the universe or re-pull their CSVs."):
        failures += 1

    # stale last_date
    ok = len(stale_date) == 0
    msg = f"Tickers with last_date != {BASELINE_LAST_DATE}: {len(stale_date)}"
    if stale_date:
        msg += f"  ({', '.join(t for t, _ in stale_date[:5])}{'...' if len(stale_date)>5 else ''})"
    if not result(msg, ok, warn=len(stale_date) <= 10,
                  action="Baseline window is inconsistent. Re-run calculate_baselines.py "
                         "after verifying all Sep 14 snapshot CSVs exist."):
        failures += 1

    # MAD ratio
    ok = len(bad_mad) == 0
    msg = f"Tickers with MAD > {MAX_MAD_RATIO}x median volume: {len(bad_mad)}"
    if bad_mad:
        worst = sorted(bad_mad, key=lambda x: -x[1])[:3]
        msg += f"  (worst: {worst})"
    if not result(msg, ok, warn=len(bad_mad) <= 10,
                  action="High MAD/median means very erratic normal-day volume. "
                         "These tickers will produce noisy signals. "
                         "Check their CSVs for data errors; consider excluding if ratio > 5x."):
        failures += 1

    # zero price
    ok = len(zero_price) == 0
    msg = f"Tickers with zero median price: {len(zero_price)}"
    if zero_price:
        msg += f"  ({', '.join(zero_price[:5])})"
    if not result(msg, ok,
                  action="Price data missing. Check CSVs for these tickers; "
                         "price is used for signal context display only, not allocation."):
        failures += 1

    # ── 4. Short-term == long-term consistency ───────────────────────────────
    mismatched = [
        t for t, d in baselines.items()
        if d.get("short_term", {}).get("median_volume") !=
           d.get("long_term", {}).get("median_volume")
    ]
    ok = len(mismatched) == 0
    if not result(f"short_term == long_term median: {len(mismatched)} mismatches", ok,
                  warn=False,
                  action="calculate_baselines.py should produce identical short/long stats "
                         "for the fixed Aug-Sep window. Data was modified externally — "
                         "re-run calculate_baselines.py from scratch."):
        failures += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if failures == 0:
        print(f"RESULT: ALL CHECKS PASSED  ({count} tickers, baseline ready)")
    else:
        print(f"RESULT: {failures} HARD FAILURE(S) — fix before competition start")
    print("=" * 60)

    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
