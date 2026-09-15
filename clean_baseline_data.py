"""
GTC 2026 - Baseline Data Cleaning Pipeline

Purpose: Clean August-September 2026 baseline data to remove data errors/glitches
         that would corrupt baseline statistics.

Key Insight (from coordinator):
- AUGUST-SEPTEMBER data = baseline period (~46 trading days)
- LOO detection will catch any competitor scouting outliers in September
- More data (46 days vs 23) → more robust median/MAD estimates
- Any "pump signals" detected = data glitches or rare scouting, both excluded

This script:
1. Processes August-September 2026 directories (20260801-20260930)
2. Applies aggressive cleaning rules (LOO - Leave One Out detection)
3. Outputs cleaned data to data/cleaned_snapshots/
4. Logs all rejections with detailed reasons
5. Generates summary statistics

Author: Jane Street SWE Team
Date: 2026-09-15 (Updated: expanded to Aug+Sep baseline)
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np
import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import logging
import shutil

# ══════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOTS_DIR = DATA_DIR / "daily_snapshots"
CLEANED_DIR = DATA_DIR / "cleaned_snapshots"
LOGS_DIR = DATA_DIR / "cleaning_logs"

# Date range: August + September 2026 baseline period (~46 trading days)
BASELINE_START = "20260801"
BASELINE_END = "20260930"

# Cleaning thresholds
THRESHOLDS = {
    'min_price': 0.0001,           # Minimum valid price (USD)
    'max_price': 10000,             # Maximum reasonable price
    'max_single_day_change': 3.0,   # 300% single-day move = suspicious
    'max_volume_spike': 20.0,       # 20x volume spike = likely glitch
    'min_valid_days_pct': 0.75,     # Need 75% valid days for baseline
    'min_days_for_ticker': 20,      # Minimum days required per ticker (was 10 for Aug-only)
}

# Create directories
CLEANED_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
# Logging Setup
# ══════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'cleaning_master.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# Core Validation Functions
# ══════════════════════════════════════════════════════════════════════

class DataValidator:
    """Validates individual CSV files against cleaning rules"""

    def __init__(self, thresholds):
        self.thresholds = thresholds
        self.rejection_reasons = []

    def validate_csv_file(self, csv_path):
        """
        Validate a single CSV file

        Returns:
            (is_valid: bool, df: DataFrame or None, reasons: list)
        """
        self.rejection_reasons = []

        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            self.rejection_reasons.append(f"CSV_PARSE_ERROR: {str(e)[:50]}")
            return False, None, self.rejection_reasons

        # Rule 1: Structural integrity
        required_cols = ['date', 'open', 'high', 'low', 'close', 'adjusted_close',
                        'volume', 'ticker', 'market']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            self.rejection_reasons.append(f"MISSING_COLUMNS: {missing_cols}")
            return False, None, self.rejection_reasons

        if len(df) == 0:
            self.rejection_reasons.append("EMPTY_FILE")
            return False, None, self.rejection_reasons

        # Get first row (should only be one row per file in daily snapshots)
        if len(df) > 1:
            self.rejection_reasons.append(f"MULTIPLE_ROWS: {len(df)} rows (expected 1)")
            return False, None, self.rejection_reasons

        row = df.iloc[0]

        # Rule 2: Invalid numeric values
        is_valid, reasons = self._validate_numeric_values(row)
        if not is_valid:
            self.rejection_reasons.extend(reasons)
            return False, None, self.rejection_reasons

        # Rule 3: OHLC constraints
        is_valid, reasons = self._validate_ohlc_constraints(row)
        if not is_valid:
            self.rejection_reasons.extend(reasons)
            return False, None, self.rejection_reasons

        return True, df, []

    def _validate_numeric_values(self, row):
        """Validate all numeric fields are sane"""
        reasons = []

        # Check prices (but allow adjusted_close to be 0 or NaN)
        price_cols = ['open', 'high', 'low', 'close']
        for col in price_cols:
            val = row[col]

            # Check for NaN/Inf
            if pd.isna(val) or np.isinf(val):
                reasons.append(f"{col.upper()}_NAN_OR_INF")
                continue

            # Check for zero or negative
            if val <= 0:
                reasons.append(f"{col.upper()}_ZERO_OR_NEGATIVE: {val}")
                continue

            # Check for absurd values
            if val < self.thresholds['min_price']:
                reasons.append(f"{col.upper()}_TOO_SMALL: {val}")

            if val > self.thresholds['max_price']:
                reasons.append(f"{col.upper()}_TOO_LARGE: {val}")

        # Check volume (allow zero, but not negative or NaN)
        vol = row['volume']
        if pd.isna(vol) or np.isinf(vol):
            reasons.append("VOLUME_NAN_OR_INF")
        elif vol < 0:
            reasons.append(f"VOLUME_NEGATIVE: {vol}")

        return len(reasons) == 0, reasons

    def _validate_ohlc_constraints(self, row):
        """Validate OHLC relationships"""
        reasons = []

        try:
            o, h, l, c = row['open'], row['high'], row['low'], row['close']

            # Skip if any are invalid
            if any(pd.isna(x) or x <= 0 for x in [o, h, l, c]):
                return True, []  # Already caught by numeric validation

            # High must be >= all others
            if h < l:
                reasons.append(f"HIGH_LESS_THAN_LOW: H={h}, L={l}")
            if h < o:
                reasons.append(f"HIGH_LESS_THAN_OPEN: H={h}, O={o}")
            if h < c:
                reasons.append(f"HIGH_LESS_THAN_CLOSE: H={h}, C={c}")

            # Low must be <= all others
            if l > o:
                reasons.append(f"LOW_GREATER_THAN_OPEN: L={l}, O={o}")
            if l > c:
                reasons.append(f"LOW_GREATER_THAN_CLOSE: L={l}, C={c}")

        except Exception as e:
            reasons.append(f"OHLC_VALIDATION_ERROR: {str(e)[:30]}")

        return len(reasons) == 0, reasons


class LOODetector:
    """Leave-One-Out anomaly detector for time series"""

    def __init__(self, thresholds):
        self.thresholds = thresholds

    def detect_anomalies(self, ticker_history):
        """
        Detect anomalous days using LOO (Leave One Out) approach

        Args:
            ticker_history: List of dicts with keys: date, close, volume

        Returns:
            List of (date, reason) tuples for anomalous days
        """
        if len(ticker_history) < 5:
            return []  # Need minimum history

        anomalies = []

        # Sort by date
        history = sorted(ticker_history, key=lambda x: x['date'])

        for i, day in enumerate(history):
            # Get previous days (excluding current)
            prev_days = history[:i]
            if len(prev_days) < 3:
                continue  # Need at least 3 days of history

            # Check price spike
            prev_prices = [d['close'] for d in prev_days if d['close'] > 0]
            if len(prev_prices) >= 3:
                median_price = np.median(prev_prices)
                if median_price > 0:
                    price_ratio = day['close'] / median_price
                    if price_ratio > self.thresholds['max_single_day_change']:
                        anomalies.append((
                            day['date'],
                            f"PRICE_SPIKE: {price_ratio:.2f}x median (close={day['close']}, median={median_price:.4f})"
                        ))

            # Check volume spike
            prev_volumes = [d['volume'] for d in prev_days if d['volume'] > 0]
            if len(prev_volumes) >= 3:
                median_volume = np.median(prev_volumes)
                if median_volume > 0 and day['volume'] > 0:
                    volume_ratio = day['volume'] / median_volume
                    if volume_ratio > self.thresholds['max_volume_spike']:
                        anomalies.append((
                            day['date'],
                            f"VOLUME_SPIKE: {volume_ratio:.2f}x median (vol={day['volume']}, median={median_volume:.0f})"
                        ))

        return anomalies

# ══════════════════════════════════════════════════════════════════════
# Main Cleaning Pipeline
# ══════════════════════════════════════════════════════════════════════

class CleaningPipeline:
    """Main data cleaning orchestrator"""

    def __init__(self):
        self.validator = DataValidator(THRESHOLDS)
        self.loo_detector = LOODetector(THRESHOLDS)

        # Statistics tracking
        self.stats = {
            'total_days_processed': 0,
            'total_files_processed': 0,
            'total_files_rejected': 0,
            'total_loo_anomalies': 0,
            'by_ticker': defaultdict(lambda: {
                'total_days': 0,
                'rejected': 0,
                'loo_anomalies': 0,
                'reasons': defaultdict(int)
            }),
            'by_rule': defaultdict(int),
            'by_date': defaultdict(lambda: {
                'total': 0,
                'rejected': 0,
                'passed': 0
            })
        }

        # Collect all ticker data for LOO analysis
        self.ticker_histories = defaultdict(list)

    def is_august_2026(self, date_str):
        """Check if date string is in August-September 2026 baseline period"""
        try:
            return BASELINE_START <= date_str <= BASELINE_END
        except:
            return False

    def process_all_days(self):
        """Process all date directories"""

        if not SNAPSHOTS_DIR.exists():
            logger.error(f"Snapshots directory not found: {SNAPSHOTS_DIR}")
            return False

        # Get all date directories
        date_dirs = sorted([d for d in SNAPSHOTS_DIR.iterdir()
                           if d.is_dir() and d.name.isdigit()])

        if not date_dirs:
            logger.error("No date directories found in daily_snapshots/")
            return False

        logger.info(f"Found {len(date_dirs)} date directories")

        # Phase 1: Validate files and collect history
        logger.info("=" * 80)
        logger.info("PHASE 1: Structural validation and data collection")
        logger.info("=" * 80)

        for date_dir in date_dirs:
            date_str = date_dir.name

            # Check if in baseline period (August-September 2026)
            if not self.is_august_2026(date_str):
                if date_str < BASELINE_START:
                    logger.warning(f"Skipping {date_str} (before baseline period)")
                elif date_str > BASELINE_END:
                    logger.warning(f"Skipping {date_str} (after baseline period - October+ monitoring data)")
                continue

            self.process_single_day_phase1(date_dir)

        # Phase 2: LOO anomaly detection
        logger.info("")
        logger.info("=" * 80)
        logger.info("PHASE 2: Leave-One-Out anomaly detection")
        logger.info("=" * 80)

        loo_anomalies = self.run_loo_detection()

        # Phase 3: Write cleaned data
        logger.info("")
        logger.info("=" * 80)
        logger.info("PHASE 3: Writing cleaned data")
        logger.info("=" * 80)

        self.write_cleaned_data(loo_anomalies)

        # Phase 4: Generate reports
        logger.info("")
        logger.info("=" * 80)
        logger.info("PHASE 4: Generating reports")
        logger.info("=" * 80)

        self.generate_reports(loo_anomalies)

        return True

    def process_single_day_phase1(self, date_dir):
        """Phase 1: Validate files and collect data"""

        date_str = date_dir.name
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        # Create day-specific log
        day_log_path = LOGS_DIR / f"{date_str}_validation.log"
        day_logger = logging.getLogger(f"day_{date_str}")
        day_logger.handlers = []
        day_logger.addHandler(logging.FileHandler(day_log_path))
        day_logger.setLevel(logging.INFO)

        day_logger.info(f"Processing {formatted_date}")

        csv_files = list(date_dir.glob("*.csv"))
        self.stats['total_days_processed'] += 1
        self.stats['by_date'][date_str]['total'] = len(csv_files)

        logger.info(f"Processing {formatted_date}: {len(csv_files)} files")

        rejected_count = 0
        passed_count = 0

        for csv_file in csv_files:
            ticker = csv_file.stem
            self.stats['total_files_processed'] += 1
            self.stats['by_ticker'][ticker]['total_days'] += 1

            is_valid, df, reasons = self.validator.validate_csv_file(csv_file)

            if not is_valid:
                self.stats['total_files_rejected'] += 1
                self.stats['by_ticker'][ticker]['rejected'] += 1
                rejected_count += 1

                # Log rejection
                reason_str = "; ".join(reasons)
                day_logger.info(f"[REJECT] {ticker}: {reason_str}")

                # Track by rule
                for reason in reasons:
                    rule_type = reason.split(':')[0]
                    self.stats['by_rule'][rule_type] += 1
                    self.stats['by_ticker'][ticker]['reasons'][rule_type] += 1

            else:
                passed_count += 1

                # Collect for LOO analysis
                row = df.iloc[0]
                self.ticker_histories[ticker].append({
                    'date': date_str,
                    'formatted_date': formatted_date,
                    'close': row['close'],
                    'volume': row['volume'],
                    'csv_path': csv_file,
                    'df': df
                })

        self.stats['by_date'][date_str]['rejected'] = rejected_count
        self.stats['by_date'][date_str]['passed'] = passed_count

        logger.info(f"  ✓ Passed: {passed_count}, ✗ Rejected: {rejected_count}")

    def run_loo_detection(self):
        """Phase 2: Run LOO anomaly detection across all tickers"""

        all_anomalies = defaultdict(list)  # {ticker: [(date, reason), ...]}

        for ticker, history in self.ticker_histories.items():
            if len(history) < 5:
                logger.info(f"Skipping LOO for {ticker}: insufficient history ({len(history)} days)")
                continue

            anomalies = self.loo_detector.detect_anomalies(history)

            if anomalies:
                all_anomalies[ticker] = anomalies
                self.stats['by_ticker'][ticker]['loo_anomalies'] = len(anomalies)
                self.stats['total_loo_anomalies'] += len(anomalies)

                logger.info(f"  {ticker}: {len(anomalies)} anomalies detected")
                for date, reason in anomalies:
                    logger.info(f"    - {date}: {reason}")

        logger.info(f"Total LOO anomalies detected: {self.stats['total_loo_anomalies']}")

        return all_anomalies

    def write_cleaned_data(self, loo_anomalies):
        """Phase 3: Write cleaned data (excluding anomalies)"""

        # Build exclusion set
        exclusion_set = set()
        for ticker, anomalies in loo_anomalies.items():
            for date, _ in anomalies:
                exclusion_set.add((ticker, date))

        logger.info(f"Exclusion set size: {len(exclusion_set)} (ticker, date) pairs")

        # Write cleaned files
        files_written = 0
        files_skipped = 0

        for ticker, history in self.ticker_histories.items():
            for entry in history:
                date_str = entry['date']

                # Check if excluded
                if (ticker, date_str) in exclusion_set:
                    files_skipped += 1
                    continue

                # Create output directory
                output_dir = CLEANED_DIR / date_str
                output_dir.mkdir(parents=True, exist_ok=True)

                # Copy file (atomic write)
                output_file = output_dir / f"{ticker}.csv"
                temp_file = output_dir / f"{ticker}.csv.tmp"

                try:
                    # Write to temp
                    entry['df'].to_csv(temp_file, index=False)

                    # Atomic rename
                    temp_file.replace(output_file)
                    files_written += 1

                except Exception as e:
                    logger.error(f"Failed to write {output_file}: {e}")
                    if temp_file.exists():
                        temp_file.unlink()

        logger.info(f"Files written: {files_written}")
        logger.info(f"Files skipped (anomalies): {files_skipped}")

    def generate_reports(self, loo_anomalies):
        """Phase 4: Generate summary reports"""

        # 1. Summary statistics JSON
        summary_file = LOGS_DIR / "summary_stats.json"

        summary_data = {
            'last_run': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'date_range': f"{BASELINE_START} to {BASELINE_END}",
            'total_days_processed': self.stats['total_days_processed'],
            'total_files_processed': self.stats['total_files_processed'],
            'total_files_rejected': self.stats['total_files_rejected'],
            'total_loo_anomalies': self.stats['total_loo_anomalies'],
            'rejection_rate_pct': round(100 * self.stats['total_files_rejected'] /
                                       max(1, self.stats['total_files_processed']), 2),
            'by_rule': dict(self.stats['by_rule']),
            'by_ticker': {
                ticker: dict(data) if not isinstance(data['reasons'], defaultdict)
                       else {**data, 'reasons': dict(data['reasons'])}
                for ticker, data in self.stats['by_ticker'].items()
            },
            'by_date': dict(self.stats['by_date'])
        }

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        logger.info(f"✓ Summary statistics: {summary_file}")

        # 2. August-September pump events CSV
        pump_events_file = LOGS_DIR / "august_september_pump_events.csv"

        with open(pump_events_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['ticker', 'date', 'reason', 'severity'])

            for ticker, anomalies in sorted(loo_anomalies.items()):
                for date, reason in anomalies:
                    # Categorize severity
                    if 'PRICE_SPIKE' in reason:
                        severity = 'HIGH'
                    elif 'VOLUME_SPIKE' in reason:
                        severity = 'MEDIUM'
                    else:
                        severity = 'LOW'

                    formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                    writer.writerow([ticker, formatted_date, reason, severity])

        logger.info(f"✓ August-September pump events: {pump_events_file}")

        # 3. Console summary
        logger.info("")
        logger.info("=" * 80)
        logger.info("CLEANING SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Baseline period:          August-September 2026 (~46 trading days)")
        logger.info(f"Total days processed:     {self.stats['total_days_processed']}")
        logger.info(f"Total files processed:    {self.stats['total_files_processed']}")
        logger.info(f"Structural rejections:    {self.stats['total_files_rejected']} "
                   f"({summary_data['rejection_rate_pct']}%)")
        logger.info(f"LOO anomalies detected:   {self.stats['total_loo_anomalies']}")
        logger.info(f"Total exclusions:         {self.stats['total_files_rejected'] + self.stats['total_loo_anomalies']}")
        logger.info("")
        logger.info("Top rejection reasons:")
        for rule, count in sorted(self.stats['by_rule'].items(),
                                 key=lambda x: x[1], reverse=True)[:10]:
            logger.info(f"  {rule}: {count}")
        logger.info("")
        logger.info(f"Output directory: {CLEANED_DIR}")
        logger.info(f"Logs directory:   {LOGS_DIR}")
        logger.info("=" * 80)


# ══════════════════════════════════════════════════════════════════════
# Main Entry Point
# ══════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 80)
    logger.info("GTC 2026 - Baseline Data Cleaning Pipeline")
    logger.info("=" * 80)
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Baseline period: {BASELINE_START} to {BASELINE_END} (August-September 2026, ~46 trading days)")
    logger.info("")

    pipeline = CleaningPipeline()
    success = pipeline.process_all_days()

    if success:
        logger.info("")
        logger.info("✓ Cleaning pipeline completed successfully")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Review august_pump_events.csv for anomalies (data glitches + rare scouting)")
        logger.info("  2. Update calculate_baselines.py to read from cleaned_snapshots/")
        logger.info("  3. Run: python calculate_baselines.py")
    else:
        logger.error("✗ Cleaning pipeline failed")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
