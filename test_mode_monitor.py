"""
BGC 2026 测试模式监控器
比赛前实时检测信号，不下单，仅观察和测试

核心功能:
- 复用production_monitor.py的信号检测逻辑
- 每30秒扫描一次
- 创建虚拟持仓（不真实下单）
- 实时观察信号准确性
- 10月11日清空测试数据（保留baseline）

作者: 五专家共识 + ME
创建时间: 2026-09-14
"""

import sys
import time
import json
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

# 复用production_monitor的核心逻辑
sys.path.append(str(Path(__file__).parent))
from production_monitor import (
    load_watchlist,
    load_baselines,
    load_prepump_exclusions,
    load_liquidity_tiers,
    fetch_live_quotes_batch,  # 使用batch函数
    fetch_all_live_quotes,    # 使用这个函数
    detect_signal,
    is_market_open,
    minutes_since_open
)

# 检查是否有异步模块
try:
    from fetch_async import fetch_all_live_quotes_parallel
    CAN_FETCH_PARALLEL = True
except ImportError:
    CAN_FETCH_PARALLEL = False


class TestModeMonitor:
    """
    测试模式监控器

    功能:
    1. 实时检测信号（复用production_monitor逻辑）
    2. 创建虚拟持仓
    3. 跟踪持仓表现
    4. 10月11日清空（保留baseline）
    """

    def __init__(self):
        import sys
        # Railway环境：使用sys.stdout确保输出不被关闭
        self._log("🔧 初始化测试模式监控器...")

        # 加载核心数据（不会被清空）
        self.watchlist = load_watchlist()
        self.baselines = load_baselines()
        self.prepump_exclusions = load_prepump_exclusions()
        self.liquidity_tiers = load_liquidity_tiers()

        self._log(f"✅ 加载 {len(self.watchlist)} 只股票")
        self._log(f"✅ 加载 {len(self.baselines)} 条baseline")
        self._log(f"✅ 排除 {len(self.prepump_exclusions)} 只prepump股票")

    def _log(self, msg):
        """安全日志输出（Railway/Streamlit兼容）"""
        try:
            import sys
            sys.stdout.write(f"{msg}\n")
            sys.stdout.flush()
        except:
            pass  # 静默失败，不影响初始化

        # 测试数据（可清空）
        self.test_signals = []  # 当前活跃信号
        self.test_positions = []  # 虚拟持仓
        self.vol_history = {}  # vol历史（用于sustained检测）

        # 统计
        self.total_scans = 0
        self.last_scan_time = None

    def run_test_scan(self):
        """
        运行一次完整扫描（30秒调用一次）

        返回:
            list: 当前检测到的信号列表
        """
        self.total_scans += 1
        self.last_scan_time = datetime.now()

        current_signals = []

        # 检查市场状态
        idx_open = is_market_open("IDX")
        set_open = is_market_open("SET")

        if not idx_open and not set_open:
            return []  # 两个市场都休市

        # 获取实时数据
        live_data_list = self._fetch_all_live_data()

        if not live_data_list:
            return []

        # 信号检测
        for ticker, market, live_data in live_data_list:
            # 跳过休市市场
            if market == "IDX" and not idx_open:
                continue
            if market == "SET" and not set_open:
                continue

            # 跳过prepump股票
            full_ticker = f"{ticker}.JK" if market == "IDX" else f"{ticker}.BK"
            if full_ticker in self.prepump_exclusions:
                continue

            # 获取baseline
            baseline_key = f"{ticker}.{market}"
            baseline = self.baselines.get(baseline_key, {})
            if not baseline or not baseline.get('avg_volume_30d'):
                continue

            # 获取流动性tier
            liquidity_tier = self.liquidity_tiers.get(full_ticker, 'L2')

            # 检测信号（复用production_monitor逻辑）
            try:
                signal = detect_signal(
                    ticker=ticker,
                    market=market,
                    live_data=live_data,
                    baseline_vol=baseline['avg_volume_30d'],
                    vol_history=self.vol_history,
                    liquidity_tier=liquidity_tier
                )

                if signal:
                    # 添加测试标记
                    signal['test_mode'] = True
                    signal['detected_at'] = datetime.now()
                    signal['scan_number'] = self.total_scans
                    current_signals.append(signal)

                    # 检查是否已有虚拟持仓
                    existing = [p for p in self.test_positions
                               if p['ticker'] == signal['ticker']
                               and p['status'] == 'OPEN']

                    if not existing:
                        # 创建虚拟持仓
                        self._create_test_position(signal)

            except Exception as e:
                self._log(f"⚠️ 检测{ticker}信号时出错: {e}")
                continue

        # 更新当前活跃信号列表
        self.test_signals = current_signals

        return current_signals

    def _fetch_all_live_data(self):
        """
        获取所有股票的实时数据
        """
        live_data_list = []

        # 使用production_monitor的fetch_all_live_quotes函数
        try:
            # fetch_all_live_quotes返回字典 {ticker: live_data}
            quotes_dict = fetch_all_live_quotes(self.watchlist)

            # 转换为list格式 [(ticker, market, live_data)]
            for ticker, market, suffix in self.watchlist:
                full_ticker = f"{ticker}{suffix}"
                if full_ticker in quotes_dict:
                    live_data_list.append((ticker, market, quotes_dict[full_ticker]))

        except Exception as e:
            self._log(f"⚠️ 获取实时数据失败: {e}")

        return live_data_list

    def _fetch_serial(self):
        """串行获取数据（fallback）- 已移除，使用上面的方法"""
        pass

    def _create_test_position(self, signal):
        """
        创建虚拟持仓
        """
        position = {
            'ticker': signal['ticker'],
            'market': signal['market'],
            'tier': signal['tier'],
            'signal_type': signal['signal'],
            'entry_time': datetime.now(),
            'entry_price': signal['price'],
            'entry_vol_ratio': signal['vol_ratio'],
            'entry_change_pct': signal['change_pct'],
            'allocation': signal['allocation'],
            'status': 'OPEN',
            'note': '🧪 测试持仓 - 未真实买入',
            'analog': signal.get('analog', ''),
            'expected_return': signal.get('expected_return', ''),
            # 实时更新字段（初始化）
            'current_price': signal['price'],
            'current_return': 0.0,
            'max_return': 0.0,
            'min_return': 0.0,
            'holding_hours': 0.0,
            'last_update': datetime.now()
        }

        self.test_positions.append(position)
        self._log(f"📝 创建测试持仓: {signal['ticker']} Tier{signal['tier']} ${signal['allocation']:,}")

    def update_test_positions(self, current_prices_dict):
        """
        更新虚拟持仓的当前价格和收益

        参数:
            current_prices_dict: {ticker: price} 字典
        """
        for pos in self.test_positions:
            if pos['status'] != 'OPEN':
                continue

            ticker = pos['ticker']

            # 获取当前价格
            if ticker in current_prices_dict:
                current_price = current_prices_dict[ticker]
                pos['current_price'] = current_price
                pos['last_update'] = datetime.now()

                # 计算收益
                entry_price = pos['entry_price']
                current_return = (current_price - entry_price) / entry_price
                pos['current_return'] = current_return

                # 更新最大/最小收益
                if current_return > pos.get('max_return', 0):
                    pos['max_return'] = current_return
                if current_return < pos.get('min_return', 0):
                    pos['min_return'] = current_return

            # 计算持有时长
            holding_time = datetime.now() - pos['entry_time']
            pos['holding_hours'] = holding_time.total_seconds() / 3600
            pos['holding_days'] = holding_time.days

    def get_test_statistics(self):
        """
        获取测试统计数据
        """
        total_positions = len(self.test_positions)
        open_positions = len([p for p in self.test_positions if p['status'] == 'OPEN'])

        # 按Tier统计
        by_tier = defaultdict(int)
        for pos in self.test_positions:
            by_tier[f"S{pos['tier']}"] += 1

        # 收益统计（仅OPEN持仓）
        open_pos = [p for p in self.test_positions if p['status'] == 'OPEN']
        if open_pos:
            returns = [p.get('current_return', 0) for p in open_pos]
            avg_return = sum(returns) / len(returns)
            max_return = max(returns)
            min_return = min(returns)

            # 盈利/亏损数量
            winners = len([r for r in returns if r > 0])
            losers = len([r for r in returns if r < 0])
        else:
            avg_return = 0
            max_return = 0
            min_return = 0
            winners = 0
            losers = 0

        return {
            'total_scans': self.total_scans,
            'last_scan_time': self.last_scan_time,
            'total_signals': len(self.test_signals),
            'total_positions': total_positions,
            'open_positions': open_positions,
            'positions_by_tier': dict(by_tier),
            'avg_return': avg_return,
            'max_return': max_return,
            'min_return': min_return,
            'winners': winners,
            'losers': losers,
            'win_rate': winners / len(open_pos) if open_pos else 0
        }

    def clear_test_data(self):
        """
        清空测试数据（10月11日调用）

        ⚠️ 重要: 不清空baseline！
        """
        self._log("\n" + "="*60)
        self._log("🧹 开始清空测试数据...")
        self._log("="*60)

        # 统计清空前数据
        stats = self.get_test_statistics()
        self._log(f"\n清空前统计:")
        self._log(f"  - 累计扫描: {stats['total_scans']} 次")
        self._log(f"  - 累计持仓: {stats['total_positions']} 个")
        self._log(f"  - 当前持仓: {stats['open_positions']} 个")
        self._log(f"  - 按Tier: {stats['positions_by_tier']}")

        # ✅ 清空测试数据
        self.test_signals = []
        self.test_positions = []
        self.vol_history = {}
        self.total_scans = 0
        self.last_scan_time = None

        self._log(f"\n✅ 已清空:")
        self._log(f"  - test_signals (实时信号)")
        self._log(f"  - test_positions (虚拟持仓)")
        self._log(f"  - vol_history (成交量历史)")
        self._log(f"  - 扫描计数器")

        # ❌ 不清空核心数据
        print(f"\n❌ 保持不变:")
        print(f"  - baselines ({len(self.baselines)} 条)")
        print(f"  - watchlist ({len(self.watchlist)} 只股票)")
        print(f"  - prepump_exclusions ({len(self.prepump_exclusions)} 只)")
        print(f"  - liquidity_tiers")

        print("\n" + "="*60)
        print("✅ 测试数据清空完成，系统准备比赛")
        print("="*60 + "\n")

    def export_test_summary(self):
        """
        导出测试总结（用户可选，不强制保存）
        返回可打印的总结字典
        """
        stats = self.get_test_statistics()

        # 按Tier分组持仓
        tier_details = defaultdict(list)
        for pos in self.test_positions:
            tier = f"S{pos['tier']}"
            tier_details[tier].append({
                'ticker': pos['ticker'],
                'entry_time': pos['entry_time'].strftime('%m-%d %H:%M'),
                'entry_price': pos['entry_price'],
                'current_return': pos.get('current_return', 0),
                'status': pos['status']
            })

        summary = {
            'test_period': {
                'total_scans': stats['total_scans'],
                'last_scan': stats['last_scan_time'].strftime('%Y-%m-%d %H:%M:%S') if stats['last_scan_time'] else 'N/A'
            },
            'signal_performance': {
                'total_signals': stats['total_positions'],
                'by_tier': stats['positions_by_tier'],
                'open_positions': stats['open_positions']
            },
            'returns': {
                'avg_return': f"{stats['avg_return']*100:.2f}%",
                'max_return': f"{stats['max_return']*100:.2f}%",
                'min_return': f"{stats['min_return']*100:.2f}%",
                'win_rate': f"{stats['win_rate']*100:.1f}%",
                'winners': stats['winners'],
                'losers': stats['losers']
            },
            'tier_details': dict(tier_details)
        }

        return summary


# ══════════════════════════════════════════════════════════════
# 命令行运行接口（可选）
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🧪 BGC 2026 测试模式监控器")
    print("="*60)

    monitor = TestModeMonitor()

    print("\n开始实时监控（每30秒扫描一次）")
    print("按 Ctrl+C 停止\n")

    try:
        while True:
            # 运行一次扫描
            signals = monitor.run_test_scan()

            # 打印结果
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 扫描 #{monitor.total_scans}")

            if signals:
                print(f"🚨 检测到 {len(signals)} 个信号:")
                for sig in signals:
                    print(f"  - {sig['ticker']} (S{sig['tier']}): {sig['signal']} | "
                          f"Vol {sig['vol_ratio']:.1f}x | Price {sig['change_pct']*100:+.1f}%")
            else:
                print("✓ 无信号")

            # 更新持仓
            current_prices = {sig['ticker']: sig['price'] for sig in signals}
            monitor.update_test_positions(current_prices)

            # 显示统计
            stats = monitor.get_test_statistics()
            print(f"📊 持仓: {stats['open_positions']} 个 | "
                  f"平均收益: {stats['avg_return']*100:+.1f}% | "
                  f"胜率: {stats['win_rate']*100:.0f}%")

            # 等待30秒
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n\n⏸️ 监控已停止")

        # 显示最终统计
        summary = monitor.export_test_summary()
        print("\n📈 测试总结:")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
