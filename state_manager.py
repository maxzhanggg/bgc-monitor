"""
状态管理器 - P0修复
整合monitor_launcher + position_manager + holding_strategy
解决Jane Street SWE发现的"状态管理灾难"问题
"""

import json
import os
from datetime import datetime
from optimized_holding_strategy import OptimizedHoldingStrategy, identify_market
from trading_calendar import calculate_competition_day, get_days_remaining

class StateManager:
    """
    统一状态管理器：
    - 追踪所有持仓
    - 每日更新价格
    - 自动判断退出时机
    - 与monitor_launcher.py集成
    """

    def __init__(self, positions_file='data/positions.json', capital=1_000_000):
        self.positions_file = positions_file
        self.total_capital = capital
        self.max_position_size = capital * 0.20  # 单仓20%（比赛规则限制）
        self.positions = {}  # {ticker: OptimizedHoldingStrategy对象}
        self.closed_positions = []

        # 风控限制
        self.max_portfolio_drawdown = 0.20  # -20%强制清仓
        self.max_concurrent_positions = 5    # 最多5个持仓

        # 加载已有持仓
        self._load_positions()

    def _load_positions(self):
        """从JSON加载持仓 - P0修复: 备份恢复"""
        if not os.path.exists(self.positions_file):
            return

        try:
            with open(self.positions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 验证数据结构
            if not isinstance(data, dict):
                raise ValueError("JSON格式错误: 根对象不是dict")
            if 'positions' not in data:
                raise ValueError("JSON格式错误: 缺少'positions'键")

            # 重建OptimizedHoldingStrategy对象
            for ticker, pos_data in data.get('positions', {}).items():
                self.positions[ticker] = OptimizedHoldingStrategy(
                    ticker=ticker,
                    entry_day=pos_data['entry_day'],
                    entry_price=pos_data['entry_price'],
                    market=pos_data['market']
                )
                self.positions[ticker].peak_price = pos_data.get('peak_price', pos_data['entry_price'])
                self.positions[ticker].current_price = pos_data.get('current_price', pos_data['entry_price'])

            self.closed_positions = data.get('closed_positions', [])

            print(f"[状态管理器] 已加载 {len(self.positions)} 个持仓")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"[严重错误] 持仓文件损坏: {e}")

            # P0修复: 尝试从备份恢复
            backup_file = self.positions_file + '.backup'
            if os.path.exists(backup_file):
                print(f"[恢复] 尝试从备份文件恢复...")
                try:
                    with open(backup_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # 重建持仓
                    for ticker, pos_data in data.get('positions', {}).items():
                        self.positions[ticker] = OptimizedHoldingStrategy(
                            ticker=ticker,
                            entry_day=pos_data['entry_day'],
                            entry_price=pos_data['entry_price'],
                            market=pos_data['market']
                        )
                        self.positions[ticker].peak_price = pos_data.get('peak_price', pos_data['entry_price'])
                        self.positions[ticker].current_price = pos_data.get('current_price', pos_data['entry_price'])

                    self.closed_positions = data.get('closed_positions', [])
                    print(f"[恢复成功] 从备份加载 {len(self.positions)} 个持仓")
                    return

                except Exception as backup_error:
                    print(f"[恢复失败] 备份文件也损坏: {backup_error}")

            # 无法恢复 - 停止运行
            print("[致命错误] 无法恢复持仓状态，请手动检查:")
            print(f"  主文件: {self.positions_file}")
            print(f"  备份文件: {backup_file}")
            raise RuntimeError(
                f"持仓文件损坏且无法从备份恢复。请手动修复或删除文件后重新运行。"
            )

    def _save_positions(self):
        """保存持仓到JSON - P0修复: 原子写入+备份"""
        data = {
            'positions': {},
            'closed_positions': self.closed_positions,
            'last_update': datetime.now().isoformat()
        }

        # 序列化持仓
        for ticker, strategy in self.positions.items():
            data['positions'][ticker] = {
                'ticker': ticker,
                'market': strategy.market,
                'entry_day': strategy.entry_day,
                'entry_price': strategy.entry_price,
                'peak_price': strategy.peak_price,
                'current_price': strategy.current_price
            }

        os.makedirs(os.path.dirname(self.positions_file), exist_ok=True)

        # P0修复: 原子写入（先写临时文件，再重命名）
        temp_file = self.positions_file + '.tmp'
        backup_file = self.positions_file + '.backup'

        try:
            # 写入临时文件
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 备份旧文件（如果存在）
            if os.path.exists(self.positions_file):
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                os.replace(self.positions_file, backup_file)

            # 原子重命名（覆盖只在写入成功后发生）
            os.replace(temp_file, self.positions_file)

        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise RuntimeError(f"保存持仓失败: {e}")

    def can_open_position(self, ticker):
        """检查是否可以开新仓"""
        # 检查1: 已有持仓
        if ticker in self.positions:
            return False, "已持有该股票"

        # 检查2: 达到最大持仓数
        if len(self.positions) >= self.max_concurrent_positions:
            return False, f"已达到最大持仓数({self.max_concurrent_positions})"

        # 检查3: 资金充足
        available_capital = self.get_available_capital()
        if available_capital < self.max_position_size:
            return False, f"可用资金不足(${available_capital:,.0f} < ${self.max_position_size:,.0f})"

        return True, "OK"

    def get_available_capital(self):
        """计算可用资金"""
        used_capital = len(self.positions) * self.max_position_size
        return self.total_capital - used_capital

    def open_position(self, ticker, entry_day, entry_price):
        """
        开新仓 - P0修复: 除零保护 + P1修复: 竞态条件

        返回: (success: bool, message: str, position_size_usd: float)
        """
        # P0修复: 验证入场价格
        if entry_price is None or entry_price <= 0:
            return False, f"无效入场价格: {entry_price}", 0

        # P1修复: 在修改前再次检查（防止竞态条件）
        if ticker in self.positions:
            return False, "已持有该股票", 0

        if len(self.positions) >= self.max_concurrent_positions:
            return False, f"已达到最大持仓数({self.max_concurrent_positions})", 0

        available_capital = self.get_available_capital()
        if available_capital < self.max_position_size:
            return False, f"可用资金不足(${available_capital:,.0f} < ${self.max_position_size:,.0f})", 0

        market = identify_market(ticker)

        # P1修复: 立即占位（防止并发开仓）
        self.positions[ticker] = None

        try:
            strategy = OptimizedHoldingStrategy(
                ticker=ticker,
                entry_day=entry_day,
                entry_price=entry_price,
                market=market
            )

            # 计算实际仓位
            shares = int(self.max_position_size / entry_price)
            actual_cost = shares * entry_price

            # 替换占位
            self.positions[ticker] = strategy
            self._save_positions()

            print(f"\n[新持仓] {ticker}")
            print(f"  市场: {market}")
            print(f"  入场: Day{entry_day} @ ${entry_price:.3f}")
            print(f"  股数: {shares:,} 股")
            print(f"  成本: ${actual_cost:,.2f}")
            print(f"  持有期: 3天 (Day{entry_day+3}退出)")

            return True, "开仓成功", actual_cost

        except Exception as e:
            # P1修复: 失败时回滚
            if ticker in self.positions:
                del self.positions[ticker]
            raise RuntimeError(f"开仓失败: {e}")

    def update_position(self, ticker, current_day, current_price):
        """
        更新持仓价格，检查是否退出

        返回: (should_exit: bool, reason: str)
        """
        if ticker not in self.positions:
            return False, "持仓不存在"

        strategy = self.positions[ticker]
        should_exit, reason = strategy.update(current_day, current_price)

        self._save_positions()

        return should_exit, reason

    def close_position(self, ticker, exit_day, exit_price, reason="手动退出"):
        """
        平仓 - P0修复: 除零保护

        返回: (success: bool, pnl_usd: float, return_pct: float)
        """
        if ticker not in self.positions:
            return False, 0, 0

        strategy = self.positions.pop(ticker)

        # P0修复: 验证价格
        if strategy.entry_price is None or strategy.entry_price <= 0:
            print(f"[错误] {ticker} 入场价格无效: {strategy.entry_price}")
            return False, 0, 0

        if exit_price is None or exit_price <= 0:
            print(f"[错误] {ticker} 出场价格无效: {exit_price}")
            # 重新插入持仓
            self.positions[ticker] = strategy
            return False, 0, 0

        shares = int(self.max_position_size / strategy.entry_price)
        entry_cost = shares * strategy.entry_price
        exit_value = shares * exit_price
        pnl = exit_value - entry_cost
        return_pct = (exit_price - strategy.entry_price) / strategy.entry_price * 100

        # 记录到已平仓
        self.closed_positions.append({
            'ticker': ticker,
            'market': strategy.market,
            'entry_day': strategy.entry_day,
            'entry_price': strategy.entry_price,
            'exit_day': exit_day,
            'exit_price': exit_price,
            'peak_price': strategy.peak_price,
            'shares': shares,
            'pnl_usd': pnl,
            'return_pct': return_pct,
            'reason': reason,
            'closed_at': datetime.now().isoformat()
        })

        self._save_positions()

        print(f"\n[平仓] {ticker}")
        print(f"  入场: Day{strategy.entry_day} @ ${strategy.entry_price:.3f}")
        print(f"  出场: Day{exit_day} @ ${exit_price:.3f}")
        print(f"  峰值: ${strategy.peak_price:.3f}")
        print(f"  盈亏: ${pnl:+,.2f} ({return_pct:+.1f}%)")
        print(f"  原因: {reason}")

        return True, pnl, return_pct

    def get_portfolio_summary(self):
        """获取投资组合摘要 - P0修复: 除零保护"""
        summary = {
            'total_capital': self.total_capital,
            'available_capital': self.get_available_capital(),
            'num_positions': len(self.positions),
            'max_positions': self.max_concurrent_positions,
            'positions': []
        }

        for ticker, strategy in self.positions.items():
            # P0修复: 验证价格
            if strategy.entry_price is None or strategy.entry_price <= 0:
                print(f"[警告] {ticker} 入场价格无效: {strategy.entry_price}，跳过")
                continue

            shares = int(self.max_position_size / strategy.entry_price)
            current_value = shares * strategy.current_price
            pnl = current_value - (shares * strategy.entry_price)
            return_pct = (strategy.current_price - strategy.entry_price) / strategy.entry_price * 100

            summary['positions'].append({
                'ticker': ticker,
                'market': strategy.market,
                'entry_day': strategy.entry_day,
                'entry_price': strategy.entry_price,
                'current_price': strategy.current_price,
                'peak_price': strategy.peak_price,
                'shares': shares,
                'pnl_usd': pnl,
                'return_pct': return_pct
            })

        return summary

    def check_risk_limits(self):
        """
        P2修复：检查风控限制（新增单仓止损 + 每日亏损限制）

        返回: (breached: bool, message: str)
        """
        if not self.positions:
            return False, "无持仓"

        # 计算总盈亏
        total_pnl = 0
        positions_to_stop_loss = []

        for ticker, strategy in self.positions.items():
            shares = int(self.max_position_size / strategy.entry_price)
            current_value = shares * strategy.current_price
            cost = shares * strategy.entry_price
            position_pnl = current_value - cost
            total_pnl += position_pnl

            # P2: 单仓-10%止损
            position_return = (strategy.current_price - strategy.entry_price) / strategy.entry_price
            if position_return < -0.10:
                positions_to_stop_loss.append({
                    'ticker': ticker,
                    'return_pct': position_return * 100
                })

        drawdown = total_pnl / self.total_capital

        # 触发条件1: 组合-20%熔断
        if drawdown < -self.max_portfolio_drawdown:
            return True, f"组合回撤{drawdown*100:.1f}% < -20%限制，触发熔断"

        # 触发条件2: 单仓-10%止损
        if positions_to_stop_loss:
            tickers_str = ', '.join([f"{p['ticker']}({p['return_pct']:.1f}%)" for p in positions_to_stop_loss])
            return True, f"单仓止损触发: {tickers_str}"

        # 触发条件3: 每日-5%亏损限制（需要tracking今日开始盈亏）
        # 简化实现：假设closed_positions中有today_closed标记
        today_closed_pnl = sum([
            p['pnl_usd'] for p in self.closed_positions
            if p.get('closed_today', False)
        ])
        daily_loss = (total_pnl + today_closed_pnl) / self.total_capital
        if daily_loss < -0.05:
            return True, f"每日亏损{daily_loss*100:.1f}% < -5%限制，暂停交易"

        return False, f"组合盈亏{drawdown*100:+.1f}%，风控正常"


if __name__ == '__main__':
    # 测试
    print("="*70)
    print("状态管理器测试")
    print("="*70)

    # 初始化
    manager = StateManager(
        positions_file='data/test_positions.json',
        capital=1_000_000
    )

    print(f"\n初始资金: ${manager.total_capital:,}")
    print(f"单仓限额: ${manager.max_position_size:,} (20%)")

    # 测试开仓
    success, msg, cost = manager.open_position('MORA.JK', entry_day=1, entry_price=0.045)
    print(f"\n开仓结果: {success}, {msg}")

    # 测试更新
    should_exit, reason = manager.update_position('MORA.JK', current_day=2, current_price=0.052)
    print(f"\nDay 2更新: should_exit={should_exit}, reason={reason}")

    should_exit, reason = manager.update_position('MORA.JK', current_day=3, current_price=0.058)
    print(f"Day 3更新: should_exit={should_exit}, reason={reason}")

    # 测试平仓
    if should_exit:
        success, pnl, return_pct = manager.close_position('MORA.JK', exit_day=3, exit_price=0.058, reason=reason)

    # 查看摘要
    summary = manager.get_portfolio_summary()
    print(f"\n{'='*70}")
    print(f"投资组合摘要:")
    print(f"  持仓数: {summary['num_positions']}/{summary['max_positions']}")
    print(f"  可用资金: ${summary['available_capital']:,}")
    print(f"{'='*70}")
