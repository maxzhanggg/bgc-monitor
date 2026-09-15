"""
自动更新Pump排除列表 - 每日收盘后运行

功能:
1. 读取当日检测到的所有信号（S1-S5）
2. 将pump股票加入排除列表（排除期30天）
3. 清理过期排除（超过30天自动恢复）
4. 保存更新后的prepump_exclusions.json

运行时机:
- 每天收盘后手动运行，或
- 使用Windows Task Scheduler定时运行（IDX收盘4:50pm, SET收盘5:00pm）
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import defaultdict

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent / "data"
PROCESSED_DIR = DATA_DIR / "processed"
SIGNALS_DIR = DATA_DIR / "signals_history"  # 存储每日信号历史

PREPUMP_FILE = PROCESSED_DIR / "prepump_exclusions_sep2026.json"
EXCLUSION_DAYS = 30  # Pump后排除天数

SIGNALS_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
# 加载/保存函数
# ══════════════════════════════════════════════════════════════════════

def load_prepump_exclusions():
    """加载现有排除列表"""
    if not PREPUMP_FILE.exists():
        return {}

    with open(PREPUMP_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_prepump_exclusions(exclusions):
    """保存排除列表（原子写入）"""
    tmp_file = PREPUMP_FILE.with_suffix('.json.tmp')

    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(exclusions, f, indent=2, ensure_ascii=False)

    tmp_file.replace(PREPUMP_FILE)

def load_today_signals(target_date=None):
    """
    加载指定日期检测到的所有信号

    信号来源:
    - production_monitor.py 运行期间会将信号写入 signals_history/YYYYMMDD.json
    - test_mode_monitor.py 测试期间信号不计入
    """
    if target_date is None:
        target_date = date.today()

    signal_file = SIGNALS_DIR / f"{target_date.strftime('%Y%m%d')}.json"

    if not signal_file.exists():
        print(f"⚠️  今日信号文件不存在: {signal_file}")
        return []

    with open(signal_file, 'r', encoding='utf-8') as f:
        return json.load(f)

# ══════════════════════════════════════════════════════════════════════
# 主逻辑
# ══════════════════════════════════════════════════════════════════════

def update_exclusions(target_date=None, dry_run=False):
    """
    更新排除列表

    参数:
        target_date: 处理的日期（默认今天）
        dry_run: True=只打印不保存
    """
    if target_date is None:
        target_date = date.today()

    print(f"\n{'='*70}")
    print(f"  自动更新Pump排除列表 - {target_date.strftime('%Y-%m-%d')}")
    print(f"{'='*70}\n")

    # 1. 加载现有排除列表
    exclusions = load_prepump_exclusions()
    original_count = len(exclusions)
    print(f"📋 当前排除列表: {original_count} 只股票")

    # 2. 清理过期排除
    today_str = target_date.isoformat()
    expired = []

    for ticker, info in list(exclusions.items()):
        exclude_until = datetime.fromisoformat(info['exclude_until']).date()
        if exclude_until < target_date:
            expired.append(ticker)
            del exclusions[ticker]

    if expired:
        print(f"🗑️  清理过期排除: {len(expired)} 只股票")
        for ticker in expired[:5]:  # 只显示前5个
            print(f"   - {ticker}")
        if len(expired) > 5:
            print(f"   ... 还有 {len(expired)-5} 只")

    # 3. 加载今日信号
    today_signals = load_today_signals(target_date)
    print(f"\n🔍 今日检测到信号: {len(today_signals)} 个")

    if not today_signals:
        print("   无新信号，跳过更新")
        return exclusions

    # 4. 添加新pump股票
    new_pumps = []
    exclude_until = target_date + timedelta(days=EXCLUSION_DAYS)

    for signal in today_signals:
        ticker = signal['ticker']

        # 如果已经在排除列表中，更新信息（记录最新pump）
        if ticker in exclusions:
            exclusions[ticker]['last_pump_date'] = today_str
            exclusions[ticker]['pump_count'] = exclusions[ticker].get('pump_count', 1) + 1
            exclusions[ticker]['latest_signal'] = {
                'tier': signal['tier'],
                'vol_ratio': signal.get('vol_ratio', 0),
                'price': signal.get('price', 0),
                'change_pct': signal.get('change_pct', 0),
            }
            print(f"   🔄 {ticker} - 再次pump（第 {exclusions[ticker]['pump_count']} 次）")
        else:
            # 新加入排除列表
            exclusions[ticker] = {
                'first_pump_date': today_str,
                'last_pump_date': today_str,
                'pump_count': 1,
                'exclude_until': exclude_until.isoformat(),
                'signal_tier': signal['tier'],
                'market': signal.get('market', ''),
                'latest_signal': {
                    'tier': signal['tier'],
                    'vol_ratio': signal.get('vol_ratio', 0),
                    'price': signal.get('price', 0),
                    'change_pct': signal.get('change_pct', 0),
                },
                'reason': f"Detected {signal.get('signal', 'PUMP')} on {today_str}"
            }
            new_pumps.append(ticker)
            tier_name = ['', 'S1_ARA_LOCK', 'S2_FLASH_SPIKE', 'S3_CONFIRMED', 'S4_SUSTAINED', 'S5_EARLY_WARNING'][signal['tier']]
            print(f"   ✅ {ticker} - {tier_name} (vol_ratio={signal.get('vol_ratio', 0):.1f}x)")

    # 5. 统计报告
    print(f"\n{'='*70}")
    print(f"📊 更新统计:")
    print(f"   - 原有排除: {original_count} 只")
    print(f"   - 过期清理: {len(expired)} 只")
    print(f"   - 新增pump: {len(new_pumps)} 只")
    print(f"   - 最终排除: {len(exclusions)} 只")
    print(f"   - 排除期限: {EXCLUSION_DAYS} 天（至 {exclude_until.strftime('%Y-%m-%d')}）")
    print(f"{'='*70}\n")

    # 6. 保存
    if not dry_run:
        save_prepump_exclusions(exclusions)
        print(f"✅ 已保存到: {PREPUMP_FILE}")
    else:
        print(f"🧪 [DRY RUN] 未保存（仅预览）")

    return exclusions

# ══════════════════════════════════════════════════════════════════════
# 命令行运行
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="自动更新Pump排除列表")
    parser.add_argument('--date', type=str, help='处理日期 (YYYY-MM-DD，默认今天)')
    parser.add_argument('--dry-run', action='store_true', help='只预览不保存')

    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    try:
        update_exclusions(target_date=target_date, dry_run=args.dry_run)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
