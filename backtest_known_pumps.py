"""
backtest_known_pumps.py — Retroactive detection test against 15 known 2024-2025 pumps.

For each historical pump, estimates which signal tier would have fired and how
many days before the stock doubled — our lead time advantage.

Decision logic after running:
  - If most pumps are caught at S2/S3 with >= 3 days lead time: thresholds are well-calibrated.
  - If many pumps are MISSED (vol_max < 2.5x): thresholds may be too strict; review S4/S5.
  - If most are caught only at S4: we're detecting late; confirm S3 threshold isn't too high.
"""

import json
import sys

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_DIR        = "C:/Users/zhang/Desktop/BGC/data"
PUMP_HIST_FILE  = f"{DATA_DIR}/processed/pump_history_summary.json"

# ── Signal thresholds (must match production_monitor.py) ─────────────────────
VOL_FLASH_EARLY  = 15.0   # S2: first 60 min
VOL_FLASH_NORMAL =  8.0   # S2: after 60 min
VOL_CONFIRMED    =  4.0   # S3
VOL_SUSTAINED    =  2.5   # S4

# Estimated day-of-detection for each tier (conservative: assumes vol_max
# was sustained, not just a one-candle spike)
DETECTION_DAY = {
    "S2_EARLY":  0.25,   # within first hour of Day 1
    "S2_NORMAL": 1.0,    # end of Day 1
    "S3":        2.0,    # Day 2 (needs sustained confirmation)
    "S4":        3.0,    # Day 3 (needs 2.5x sustained 6/24 checks)
    "MISSED":    None,
}


def classify(vol_max):
    """Return the earliest signal tier that would have fired given vol_max."""
    if vol_max >= VOL_FLASH_EARLY:
        return "S2_EARLY"
    if vol_max >= VOL_FLASH_NORMAL:
        return "S2_NORMAL"
    if vol_max >= VOL_CONFIRMED:
        return "S3"
    if vol_max >= VOL_SUSTAINED:
        return "S4"
    return "MISSED"


def load_pumps():
    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            with open(PUMP_HIST_FILE, encoding=enc) as f:
                return json.load(f)
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            print(f"[FAIL]  Pump history file not found: {PUMP_HIST_FILE}")
            sys.exit(1)
    print("[FAIL]  Could not decode pump history file.")
    sys.exit(1)


def main():
    pumps = load_pumps()
    if not pumps:
        print("[FAIL]  Pump history is empty.")
        sys.exit(1)

    print("=" * 70)
    print(f"BACKTEST: KNOWN PUMP DETECTION  ({len(pumps)} pumps, 2024-2025)")
    print("=" * 70)
    print(f"{'Ticker':<14} {'Mkt':<12} {'vol_max':>8} {'cum_ret':>8} "
          f"{'days_2x':>8} {'Signal':<12} {'Lead(d)':>8}")
    print("-" * 70)

    caught = 0
    missed = 0
    total_lead = 0.0
    lead_samples = 0

    tier_counts = {"S2_EARLY": 0, "S2_NORMAL": 0, "S3": 0, "S4": 0, "MISSED": 0}

    for p in pumps:
        ticker    = p.get("ticker", "?")
        market    = p.get("market", "?")
        vol_max   = float(p.get("vol_max", 0))
        cum_ret   = float(p.get("cum_return", 0))
        days_2x   = float(p.get("days_2x", 0))

        tier      = classify(vol_max)
        det_day   = DETECTION_DAY[tier]
        tier_counts[tier] += 1

        if tier == "MISSED":
            missed += 1
            lead_str = "  --"
        else:
            caught += 1
            lead = days_2x - det_day if days_2x > 0 else 0
            lead = max(lead, 0)
            lead_str = f"{lead:>6.1f}d"
            if days_2x > 0:
                total_lead += lead
                lead_samples += 1

        tier_label = tier.replace("_", " ")
        print(f"{ticker:<14} {market:<12} {vol_max:>7.1f}x {cum_ret:>7.0%} "
              f"{days_2x:>7.1f}d  {tier_label:<12} {lead_str}")

    avg_lead = total_lead / lead_samples if lead_samples > 0 else 0

    print("=" * 70)
    print(f"\nSUMMARY")
    print(f"  Detected : {caught}/{len(pumps)}  ({caught/len(pumps)*100:.0f}%)")
    print(f"  Missed   : {missed}/{len(pumps)}  (vol_max < {VOL_SUSTAINED}x on peak day)")
    print(f"  Avg lead : {avg_lead:.1f} days before 2x (on detected pumps)")
    print()
    print(f"  Tier breakdown:")
    print(f"    S2 early  (>= {VOL_FLASH_EARLY}x)  : {tier_counts['S2_EARLY']} pumps")
    print(f"    S2 normal (>= {VOL_FLASH_NORMAL}x)   : {tier_counts['S2_NORMAL']} pumps")
    print(f"    S3        (>= {VOL_CONFIRMED}x)   : {tier_counts['S3']} pumps")
    print(f"    S4        (>= {VOL_SUSTAINED}x)   : {tier_counts['S4']} pumps")
    print(f"    MISSED    (< {VOL_SUSTAINED}x)    : {tier_counts['MISSED']} pumps")

    print()
    if missed == 0:
        print("  [PASS]  All known pumps would have been detected.")
    elif missed <= 2:
        print(f"  [WARN]  {missed} pump(s) below threshold — review if vol_max was truly < 2.5x")
        print("          or if a slower accumulation pattern needs an S5 threshold tweak.")
    else:
        print(f"  [FAIL]  {missed} pumps missed — thresholds may be too strict for this market.")
        print("          Consider lowering VOL_SUSTAINED or adding an S5 pre-watch tier.")

    if avg_lead >= 3:
        print(f"  [PASS]  Average {avg_lead:.1f}-day lead time — sufficient to enter before the crowd.")
    elif avg_lead >= 1:
        print(f"  [WARN]  Average {avg_lead:.1f}-day lead — still competitive but tight.")
        print("          Consider monitoring intraday more frequently at competition start.")
    else:
        print(f"  [FAIL]  Average {avg_lead:.1f}-day lead — detection may be too late for max gain.")

    print("=" * 70)
    sys.exit(0 if missed <= 2 else 1)


if __name__ == "__main__":
    main()
