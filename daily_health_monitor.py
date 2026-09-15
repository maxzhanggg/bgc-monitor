"""
daily_health_monitor.py — Competition-period daily system health report.

Run once per day (e.g., 08:20 BJT, before the market opens) to confirm the
system is ready to monitor. Outputs a concise status block covering data
freshness, signal history, current positions, and competition progress.

Exit codes: 0 = all green, 1 = warnings/failures that need attention.
"""

import json
import os
import sys
import csv
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Paths (mirror production_monitor.py) ────────────────────────────────────
DATA_DIR            = Path("C:/Users/zhang/Desktop/BGC/data")
BASELINE_FILE       = DATA_DIR / "processed" / "baselines_aug_sep_2026_clean.json"
PREPUMP_FILE        = DATA_DIR / "processed" / "prepump_exclusions_sep2026.json"
SIGNALS_HISTORY_DIR = DATA_DIR / "signals_history"
POSITIONS_FILE      = DATA_DIR / "positions.json"
LOG_FILE            = DATA_DIR / "alerts" / "alert_log.csv"
SNAPSHOTS_DIR       = DATA_DIR / "snapshots"

# ── Competition parameters ───────────────────────────────────────────────────
COMPETITION_START = date(2026, 10, 13)
COMPETITION_END   = date(2026, 11, 13)
CAPITAL           = 1_000_000
MAX_SLOTS         = 5
ALLOCATION_BY_TIER = {1: 200_000, 2: 200_000, 3: 150_000, 4: 100_000}


# ── Helpers ──────────────────────────────────────────────────────────────────
def tag(ok, warn=False):
    return "[OK  ]" if ok else ("[WARN]" if warn else "[FAIL]")


def load_json(path, encoding="utf-8"):
    for enc in [encoding, "utf-8-sig", "latin-1"]:
        try:
            with open(path, encoding=enc) as f:
                return json.load(f)
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
    return None


def trading_days_between(start, end):
    """Approximate trading days (Mon-Fri) between two dates inclusive."""
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def main():
    today     = date.today()
    now       = datetime.now()
    today_str = today.strftime("%Y%m%d")

    print("=" * 65)
    print(f"BGC 2026 DAILY HEALTH MONITOR  —  {today.strftime('%Y-%m-%d %A')}")
    print("=" * 65)

    # ── 1. Competition timeline ──────────────────────────────────────────────
    in_competition = COMPETITION_START <= today <= COMPETITION_END
    if today < COMPETITION_START:
        days_until = (COMPETITION_START - today).days
        print(f"\n[PREP]  Competition starts in {days_until} day(s) "
              f"({COMPETITION_START}). System in pre-competition mode.")
    elif today > COMPETITION_END:
        print(f"\n[DONE]  Competition ended {COMPETITION_END}. Final report only.")
        in_competition = False
    else:
        elapsed  = trading_days_between(COMPETITION_START, today)
        total    = trading_days_between(COMPETITION_START, COMPETITION_END)
        remaining = trading_days_between(today, COMPETITION_END)
        print(f"\n[COMP]  Day {elapsed}/{total} trading days  "
              f"({remaining} remaining, ends {COMPETITION_END})")

    failures = 0
    warnings = 0

    # ── 2. Baseline file ─────────────────────────────────────────────────────
    print("\n--- DATA INTEGRITY ---")
    baselines = load_json(BASELINE_FILE)
    ok = baselines is not None and len(baselines) >= 213
    t  = tag(ok)
    print(f"  {t}  Baseline: {len(baselines) if baselines else 0} tickers loaded "
          f"({'OK' if ok else 'MISSING/INCOMPLETE — run verify_baseline_health.py'})")
    if not ok:
        failures += 1

    # ── 3. Today's snapshot data ─────────────────────────────────────────────
    snap_dir = SNAPSHOTS_DIR / today_str
    if snap_dir.exists():
        snap_files = list(snap_dir.glob("*.csv"))
        ok_snap = len(snap_files) >= 200
        t = tag(ok_snap, warn=100 <= len(snap_files) < 200)
        print(f"  {t}  Snapshots today: {len(snap_files)} CSV files in {today_str}/")
        if not ok_snap:
            if len(snap_files) < 100:
                failures += 1
                print(f"         -> Auto-collector may not have run. "
                      f"Check Task Scheduler: BGC_2026_DataCollector.")
            else:
                warnings += 1
    else:
        # Check yesterday's as fallback (before today's collection)
        yesterday_str = (today - timedelta(days=1)).strftime("%Y%m%d")
        yest_dir = SNAPSHOTS_DIR / yesterday_str
        if yest_dir.exists():
            yest_files = list(yest_dir.glob("*.csv"))
            t = tag(False, warn=True)
            print(f"  {t}  No snapshot dir for today yet. "
                  f"Yesterday: {len(yest_files)} files. "
                  f"Collection scheduled 08:30?")
            warnings += 1
        else:
            print(f"  [FAIL]  No snapshot data for {today_str} or {yesterday_str}.")
            print(f"         -> Run auto_collector.py manually or check scheduler.")
            failures += 1

    # ── 4. Exclusions file ───────────────────────────────────────────────────
    exclusions = load_json(PREPUMP_FILE)
    if exclusions is not None:
        excl_count = len(exclusions) if isinstance(exclusions, (list, dict)) else 0
        print(f"  [OK  ]  Exclusions file: {excl_count} tickers excluded "
              f"(pre-pump/already-pumped)")
    else:
        print(f"  [WARN]  Exclusions file not found: {PREPUMP_FILE.name}")
        print(f"         -> Run update_exclusions_daily.py or check data pipeline.")
        warnings += 1

    # ── 5. Signal history ────────────────────────────────────────────────────
    print("\n--- SIGNALS ---")
    signal_files = sorted(SIGNALS_HISTORY_DIR.glob("*.json")) if \
        SIGNALS_HISTORY_DIR.exists() else []

    today_signals = []
    recent_signals = []  # last 3 days
    cutoff_3d = today - timedelta(days=3)

    for sf in signal_files:
        try:
            sig = load_json(sf)
            if sig is None:
                continue
            sigs = sig if isinstance(sig, list) else [sig]
            for s in sigs:
                ts = s.get("timestamp", s.get("date", ""))
                try:
                    sig_date = datetime.fromisoformat(ts).date() if ts else None
                except Exception:
                    sig_date = None
                if sig_date == today:
                    today_signals.append(s)
                if sig_date and sig_date >= cutoff_3d:
                    recent_signals.append(s)
        except Exception:
            continue

    if today_signals:
        print(f"  [OK  ]  Today's signals: {len(today_signals)} fired")
        for s in sorted(today_signals, key=lambda x: x.get("tier", 9)):
            ticker = s.get("ticker", "?")
            tier   = s.get("tier", "?")
            alloc  = s.get("allocation", 0)
            vr     = s.get("vol_ratio", 0)
            print(f"           S{tier} {ticker:<10}  vol={vr:.1f}x  "
                  f"alloc=${alloc:,}")
    elif in_competition:
        print(f"  [OK  ]  No signals fired today (normal — ~1-3 pumps/month expected)")
    else:
        print(f"  [INFO]  No signals today (pre-competition, system warming up)")

    if recent_signals:
        tickers_3d = list({s.get("ticker") for s in recent_signals})
        print(f"  [INFO]  Last 3 days: {len(recent_signals)} signal(s) "
              f"across {tickers_3d}")

    # ── 6. Alert log last entry ──────────────────────────────────────────────
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                last = rows[-1]
                last_ts = last.get("timestamp", last.get("time", "unknown"))
                print(f"  [OK  ]  Alert log: {len(rows)} entries, "
                      f"last at {last_ts}")
            else:
                print(f"  [INFO]  Alert log exists but is empty.")
        except Exception as e:
            print(f"  [WARN]  Alert log unreadable: {e}")
            warnings += 1
    else:
        print(f"  [INFO]  Alert log not yet created (normal before first signal).")

    # ── 7. Positions ─────────────────────────────────────────────────────────
    print("\n--- POSITIONS ---")
    positions_raw = load_json(POSITIONS_FILE)
    if positions_raw is None:
        positions_raw = {}

    # Normalise to dict keyed by ticker regardless of storage format.
    # File may be {"positions": {...}, "closed_positions": [...]} or a flat
    # dict of positions, or a list of position objects.
    if isinstance(positions_raw, dict) and "positions" in positions_raw:
        inner = positions_raw["positions"]
        if isinstance(inner, dict):
            positions = inner
        elif isinstance(inner, list):
            positions = {p.get("ticker", f"pos_{i}"): p for i, p in enumerate(inner)}
        else:
            positions = {}
    elif isinstance(positions_raw, list):
        positions = {p.get("ticker", f"pos_{i}"): p for i, p in enumerate(positions_raw)}
    elif isinstance(positions_raw, dict):
        positions = positions_raw
    else:
        positions = {}

    if positions:
        open_pos = {k: v for k, v in positions.items()
                    if v.get("status") not in ("closed", "exited")}
        closed   = len(positions) - len(open_pos)
        slots_used = len(open_pos)
        slots_free = MAX_SLOTS - slots_used

        total_allocated = sum(
            v.get("allocation", v.get("size", 0))
            for v in open_pos.values()
        )
        cash_deployed_pct = total_allocated / CAPITAL * 100

        print(f"  [OK  ]  Open positions: {slots_used}/{MAX_SLOTS} slots used  "
              f"({slots_free} free)")
        print(f"  [INFO]  Capital deployed: ${total_allocated:,}  "
              f"({cash_deployed_pct:.1f}% of ${CAPITAL:,})")
        if closed:
            print(f"  [INFO]  Closed positions: {closed}")

        for ticker, pos in open_pos.items():
            entry  = pos.get("entry_price", pos.get("price", 0))
            alloc  = pos.get("allocation", pos.get("size", 0))
            tier   = pos.get("tier", "?")
            entry_date = pos.get("entry_date", pos.get("date", "?"))
            print(f"           S{tier} {ticker:<10}  entry=${entry}  "
                  f"alloc=${alloc:,}  since {entry_date}")

        if slots_free == 0:
            print(f"  [WARN]  All {MAX_SLOTS} slots full — "
                  f"new signals will be logged but not acted on until a position closes.")
            warnings += 1
    elif not in_competition:
        print(f"  [INFO]  No positions yet (pre-competition).")
    else:
        print(f"  [INFO]  No open positions. All {MAX_SLOTS} slots available.")

    # ── 8. Country exposure check ────────────────────────────────────────────
    if isinstance(positions, dict) and positions:
        MAX_COUNTRY_48H = 250_000
        now_dt = datetime.now()
        cutoff_48h = now_dt - timedelta(hours=48)

        country_48h = {}
        for ticker, pos in positions.items():
            if pos.get("status") in ("closed", "exited"):
                continue
            try:
                entry_dt = datetime.fromisoformat(
                    pos.get("entry_date", pos.get("date", ""))
                )
            except Exception:
                continue
            if entry_dt >= cutoff_48h:
                mkt = pos.get("market", "unknown")
                alloc = pos.get("allocation", pos.get("size", 0))
                country_48h[mkt] = country_48h.get(mkt, 0) + alloc

        for mkt, total in country_48h.items():
            ok_exp = total <= MAX_COUNTRY_48H
            t = tag(ok_exp, warn=total > MAX_COUNTRY_48H * 0.8)
            print(f"  {t}  {mkt} 48h exposure: ${total:,} "
                  f"(limit ${MAX_COUNTRY_48H:,})")
            if not ok_exp:
                failures += 1
                print(f"         -> Do NOT open new {mkt} positions until 48h window clears.")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    if failures == 0 and warnings == 0:
        print(f"SYSTEM STATUS: ALL GREEN  — ready to monitor")
    elif failures == 0:
        print(f"SYSTEM STATUS: {warnings} WARNING(S)  — monitor but proceed")
    else:
        print(f"SYSTEM STATUS: {failures} FAILURE(S), {warnings} WARNING(S)  "
              f"— fix before market open")
    print(f"Run time: {now.strftime('%H:%M:%S')}")
    print("=" * 65)

    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
