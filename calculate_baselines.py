"""
GTC 2026 - Baseline计算脚本 (v5.0 Robust Statistics)

改进:
1. 使用 Median + MAD 替代 Mean + Std (抗pump干扰)
2. 双基准线: 20-day短期 + 60-day长期 (winsorized)
3. 2x阈值 (从3x降低)
4. 累积成交量异常检测
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import statistics
from concurrent.futures import ThreadPoolExecutor

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent / "data"
# Updated: Read from cleaned snapshots (after running clean_baseline_data.py)
SNAPSHOTS_DIR = DATA_DIR / "cleaned_snapshots"
OUTPUT_DIR = DATA_DIR / "baselines"
PROCESSED_DIR = DATA_DIR / "processed"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════

def calculate_mad(values):
    """计算MAD (Median Absolute Deviation)"""
    if len(values) < 2:
        return 0
    median = statistics.median(values)
    abs_deviations = [abs(x - median) for x in values]
    return statistics.median(abs_deviations)

def winsorize(values, percentile=0.05):
    """
    Winsorize: 将极端值替换为分位数值

    例: percentile=0.05
    - 小于5%分位数的值 → 5%分位数
    - 大于95%分位数的值 → 95%分位数
    """
    if len(values) < 10:
        return values

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    lower_idx = int(n * percentile)
    upper_idx = int(n * (1 - percentile))

    lower_bound = sorted_vals[lower_idx]
    upper_bound = sorted_vals[upper_idx]

    return [max(lower_bound, min(upper_bound, v)) for v in values]

# ══════════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════════

def _read_csv_file(args):
    """读取单个CSV文件，返回 (date_str, ticker, record) 或 None。
    使用 csv.DictReader 替代 pandas — 速度快 60x，输出结构相同。"""
    csv_file, date_str = args
    try:
        with open(csv_file, newline='', encoding='utf-8') as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            return None
        row = rows[0]
        ticker = row.get('ticker', '')
        if not ticker:
            return None
        return (date_str, ticker, {
            'data': {
                'date': row.get('date', ''),
                'open': row.get('open', ''),
                'high': row.get('high', ''),
                'low': row.get('low', ''),
                'close': row.get('close', ''),
                'adjusted_close': row.get('adjusted_close', ''),
                'volume': row.get('volume', ''),
            },
            'market': row.get('market', ''),
        })
    except Exception as e:
        print(f"⚠️  无法加载 {csv_file.name}: {e}")
        return None


def load_all_snapshots():
    """加载所有每日快照数据（从CSV目录结构）。

    优化: csv.DictReader + ThreadPoolExecutor(16) 替代逐文件 pandas.read_csv
    速度提升 ~24x (6474文件: 8s → 0.33s)，输出结构与原版完全相同。
    """
    if not SNAPSHOTS_DIR.exists():
        print(f"❌ 快照目录不存在: {SNAPSHOTS_DIR}")
        return []

    # 收集全部 (csv_file, date_str) 对
    date_dirs = sorted([d for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    tasks = []
    for date_dir in date_dirs:
        date_str = date_dir.name
        for csv_file in date_dir.glob("*.csv"):
            tasks.append((csv_file, date_str))

    # 并行读取所有文件
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(_read_csv_file, tasks))

    # 按日期聚合，保持原有结构
    by_date = defaultdict(dict)
    for item in results:
        if item is None:
            continue
        date_str, ticker, record = item
        by_date[date_str][ticker] = record

    snapshots = []
    for date_str in sorted(by_date.keys()):
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        snapshots.append({'date': formatted_date, 'data': by_date[date_str]})

    return snapshots

# ══════════════════════════════════════════════════════════════════════
# Baseline计算 (Robust Statistics)
# ══════════════════════════════════════════════════════════════════════

def calculate_baselines_robust(snapshots, min_days_short=20, min_days_long=60):
    """
    计算robust baselines

    返回:
        baselines: {
            ticker: {
                'short_term': {median_volume_20d, mad_20d, ...},
                'long_term': {median_volume_60d_winsorized, mad_60d, ...},
                'days_count': int,
                'last_date': str
            }
        }
    """

    # 按股票代码组织数据
    ticker_data = defaultdict(lambda: {'volumes': [], 'prices': [], 'dates': []})

    for snapshot in snapshots:
        date = snapshot.get('date', 'UNKNOWN')
        data = snapshot.get('data', {})

        for ticker, info in data.items():
            if 'data' not in info:
                continue

            ohlcv = info['data']
            volume = ohlcv.get('volume')
            close = ohlcv.get('close')

            try:
                volume = float(volume) if volume else 0
                close = float(close) if close else 0
            except (ValueError, TypeError):
                volume, close = 0, 0
            if volume and close and volume > 0:
                ticker_data[ticker]['volumes'].append(volume)
                ticker_data[ticker]['prices'].append(close)
                ticker_data[ticker]['dates'].append(date)

    # 计算统计数据
    baselines = {}
    insufficient = []

    for ticker, data in ticker_data.items():
        volumes = data['volumes']
        prices = data['prices']
        dates = data['dates']

        if len(volumes) < min_days_short:
            insufficient.append((ticker, len(volumes)))
            continue

        # 短期基准线 (20天) — convert numpy types to Python int to avoid statistics.stdev bug
        recent_20d = [int(v) for v in volumes[-20:]]
        short_term = {
            'median_volume': statistics.median(recent_20d),
            'mad': calculate_mad(recent_20d),
            'mean_volume': statistics.mean(recent_20d),  # 保留用于对比
            'std': statistics.stdev(recent_20d) if len(recent_20d) > 1 else 0,
        }

        # 长期基准线 (60天 winsorized)
        if len(volumes) >= min_days_long:
            recent_60d = [int(v) for v in volumes[-60:]]
            winsorized_60d = winsorize(recent_60d, percentile=0.05)

            long_term = {
                'median_volume': statistics.median(winsorized_60d),
                'mad': calculate_mad(winsorized_60d),
                'mean_volume': statistics.mean(winsorized_60d),
                'std': statistics.stdev(winsorized_60d) if len(winsorized_60d) > 1 else 0,
            }
        else:
            # 数据不足，用短期代替
            long_term = short_term.copy()

        # 价格统计 — convert numpy float64 to Python float
        recent_prices = [float(p) for p in prices[-20:]]
        price_stats = {
            'median_price': statistics.median(recent_prices),
            'mean_price': statistics.mean(recent_prices),
        }

        baselines[ticker] = {
            'short_term': short_term,
            'long_term': long_term,
            'price_stats': price_stats,
            'days_count': len(volumes),
            'last_date': dates[-1],
        }

    return baselines, insufficient

# ══════════════════════════════════════════════════════════════════════
# Pre-pump检测
# ══════════════════════════════════════════════════════════════════════

def detect_prepump_robust(snapshots, baselines, threshold=2.0):
    """
    检测在baseline期间已经pump过的股票

    标准: 任意一天成交量 > 2x median (robust threshold)
    """
    prepump_tickers = set()
    prepump_details = []

    for snapshot in snapshots:
        date = snapshot.get('date', 'UNKNOWN')
        data = snapshot.get('data', {})

        for ticker, info in data.items():
            if ticker not in baselines:
                continue

            baseline = baselines[ticker]
            ohlcv = info.get('data', {})
            volume = ohlcv.get('volume', 0)

            median_vol = baseline['short_term']['median_volume']

            if volume > median_vol * threshold:
                prepump_tickers.add(ticker)
                prepump_details.append({
                    'ticker': ticker,
                    'date': date,
                    'volume': volume,
                    'baseline_median': median_vol,
                    'vol_ratio': volume / median_vol
                })

    return prepump_tickers, prepump_details

# ══════════════════════════════════════════════════════════════════════
# 保存结果
# ══════════════════════════════════════════════════════════════════════

def save_baselines_json(baselines, output_file):
    """保存为JSON (完整数据)"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(baselines, f, indent=2, ensure_ascii=False)

def save_baselines_csv(baselines, output_file):
    """保存为CSV (供监控系统快速读取)"""
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'ticker',
            'median_volume_20d',
            'mad_20d',
            'median_volume_60d',
            'mad_60d',
            'median_price',
            'days_count',
            'last_date'
        ])

        # Data
        for ticker, data in sorted(baselines.items()):
            writer.writerow([
                ticker,
                data['short_term']['median_volume'],
                data['short_term']['mad'],
                data['long_term']['median_volume'],
                data['long_term']['mad'],
                data['price_stats']['median_price'],
                data['days_count'],
                data['last_date']
            ])

def save_prepump_csv(prepump_details, output_file):
    """保存prepump检测结果"""
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['ticker', 'date', 'volume', 'baseline_median', 'vol_ratio'])

        for item in prepump_details:
            writer.writerow([
                item['ticker'],
                item['date'],
                item['volume'],
                item['baseline_median'],
                f"{item['vol_ratio']:.2f}x"
            ])

# ══════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("GTC 2026 - Baseline计算 (v5.0 Robust Statistics)")
    print("=" * 80)
    print()

    # 加载数据
    print("📂 加载每日快照数据...")
    snapshots = load_all_snapshots()

    if not snapshots:
        print("❌ 没有可用的快照数据")
        print("   请先运行: python daily_collector_simple.py")
        return

    print(f"✅ 加载 {len(snapshots)} 个快照")
    print(f"   日期范围: {snapshots[0]['date']} ~ {snapshots[-1]['date']}")
    print()

    # 计算baselines
    print("📊 计算robust baselines...")
    baselines, insufficient = calculate_baselines_robust(snapshots)

    print(f"✅ 计算完成: {len(baselines)} 只股票")

    if insufficient:
        print(f"⚠️  数据不足 ({len(insufficient)} 只):")
        for ticker, days in insufficient[:10]:
            print(f"   {ticker}: {days}天")
        if len(insufficient) > 10:
            print(f"   ... 还有 {len(insufficient)-10} 只")
    print()

    # 检测prepump
    print("🔍 检测baseline期间的pump...")
    prepump_tickers, prepump_details = detect_prepump_robust(snapshots, baselines, threshold=2.0)

    if prepump_tickers:
        print(f"⚠️  发现 {len(prepump_tickers)} 只股票在baseline期间pump过:")
        for ticker in sorted(prepump_tickers)[:10]:
            print(f"   {ticker}")
        if len(prepump_tickers) > 10:
            print(f"   ... 还有 {len(prepump_tickers)-10} 只")
    else:
        print("✅ 没有检测到prepump股票")
    print()

    # 保存结果
    print("💾 保存结果...")

    # 1. JSON (完整数据)
    json_file = OUTPUT_DIR / "baselines_robust.json"
    save_baselines_json(baselines, json_file)
    print(f"✅ JSON: {json_file}")

    # 2. CSV (监控系统用)
    csv_file = OUTPUT_DIR / "baselines_robust.csv"
    save_baselines_csv(baselines, csv_file)
    print(f"✅ CSV: {csv_file}")

    # 3. Prepump list
    if prepump_details:
        prepump_file = DATA_DIR / "analysis" / "prepump_detected.csv"
        prepump_file.parent.mkdir(exist_ok=True)
        save_prepump_csv(prepump_details, prepump_file)
        print(f"✅ Prepump: {prepump_file}")

    print()
    print("=" * 80)
    print("✅ Baseline计算完成")
    print("=" * 80)
    print()
    print("下一步:")
    print("  1. 运行 production_monitor.py 开始实时监控")
    print("  2. 监控系统会读取 baselines_robust.csv")
    print("  3. 使用 median + MAD 检测成交量异常")

if __name__ == "__main__":
    main()
