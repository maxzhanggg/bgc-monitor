"""
持仓管理模块
管理开仓、平仓、持仓跟踪
"""

import pandas as pd
import os
from datetime import datetime

class PositionManager:
    def __init__(self, initial_capital=1_000_000, max_positions=5, position_size_pct=0.20):
        """
        初始化持仓管理器

        Args:
            initial_capital: 初始资金 (默认 $1,000,000)
            max_positions: 最大持仓数量 (默认 5个)
            position_size_pct: 单仓位资金占比 (默认 20% = $200,000)
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct

        self.positions = {}  # {ticker: {'shares': int, 'entry_price': float, 'entry_day': int, 'peak_price': float}}
        self.history = []    # 交易历史记录

    def can_open_position(self):
        """检查是否可以开新仓"""
        return len(self.positions) < self.max_positions

    def open_position(self, ticker, price, competition_day):
        """
        开仓

        Args:
            ticker: 股票代码
            price: 开仓价格
            competition_day: 比赛日（Day 20+）

        Returns:
            bool: 是否成功开仓
        """
        if not self.can_open_position():
            print(f"[持仓管理] 无法开仓 {ticker}: 已达最大持仓数 {self.max_positions}")
            return False

        if ticker in self.positions:
            print(f"[持仓管理] 无法开仓 {ticker}: 已持有该股票")
            return False

        # 计算仓位大小
        position_value = self.cash * self.position_size_pct
        shares = int(position_value / price)

        if shares == 0:
            print(f"[持仓管理] 无法开仓 {ticker}: 资金不足（需要 ${price:.2f}）")
            return False

        cost = shares * price

        # 执行开仓
        self.cash -= cost
        self.positions[ticker] = {
            'shares': shares,
            'entry_price': price,
            'entry_day': competition_day,
            'peak_price': price,
            'cost': cost
        }

        # 记录交易
        self.history.append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'competition_day': competition_day,
            'action': 'BUY',
            'ticker': ticker,
            'price': price,
            'shares': shares,
            'cost': cost,
            'cash_after': self.cash
        })

        print(f"[持仓管理] ✅ 开仓 {ticker}: ${price:.4f} × {shares}股 = ${cost:.2f} (Day {competition_day})")
        return True

    def close_position(self, ticker, price, competition_day, reason=""):
        """
        平仓

        Args:
            ticker: 股票代码
            price: 平仓价格
            competition_day: 比赛日
            reason: 平仓原因

        Returns:
            bool: 是否成功平仓
        """
        if ticker not in self.positions:
            print(f"[持仓管理] 无法平仓 {ticker}: 未持有该股票")
            return False

        pos = self.positions[ticker]
        shares = pos['shares']
        entry_price = pos['entry_price']
        proceeds = shares * price

        # 计算盈亏
        pnl = proceeds - pos['cost']
        pnl_pct = (price / entry_price - 1) * 100

        # 执行平仓
        self.cash += proceeds
        del self.positions[ticker]

        # 记录交易
        self.history.append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'competition_day': competition_day,
            'action': 'SELL',
            'ticker': ticker,
            'price': price,
            'shares': shares,
            'proceeds': proceeds,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'cash_after': self.cash,
            'reason': reason
        })

        emoji = "🎉" if pnl > 0 else "❌"
        print(f"[持仓管理] {emoji} 平仓 {ticker}: ${price:.4f} × {shares}股 = ${proceeds:.2f}")
        print(f"            盈亏: ${pnl:+.2f} ({pnl_pct:+.2f}%) | 原因: {reason}")

        return True

    def update_position(self, ticker, current_price):
        """更新持仓的峰值价格"""
        if ticker in self.positions:
            if current_price > self.positions[ticker]['peak_price']:
                self.positions[ticker]['peak_price'] = current_price

    def check_exit_conditions(self, ticker, current_price, competition_day, force_exit_day=28):
        """
        检查是否应该平仓

        策略：
        1. 持有3天后自动卖出
        2. 峰值后回撤5%止损
        3. Day 28强制清仓

        Returns:
            tuple: (should_exit: bool, reason: str)
        """
        if ticker not in self.positions:
            return False, ""

        pos = self.positions[ticker]
        entry_day = pos['entry_day']
        entry_price = pos['entry_price']
        peak_price = pos['peak_price']
        hold_days = competition_day - entry_day

        # 规则1: 持有3天
        if hold_days >= 3:
            return True, f"持有{hold_days}天"

        # 规则2: 峰值后跌5%
        drawdown_from_peak = (current_price / peak_price - 1) * 100
        if drawdown_from_peak <= -5.0:
            return True, f"峰值回撤{drawdown_from_peak:.1f}%"

        # 规则3: Day 28强制清仓
        if competition_day >= force_exit_day:
            return True, f"Day {force_exit_day}强制清仓"

        return False, ""

    def get_portfolio_value(self, current_prices):
        """
        计算当前组合总价值

        Args:
            current_prices: {ticker: price} 字典

        Returns:
            float: 总价值
        """
        position_value = sum(
            self.positions[ticker]['shares'] * current_prices.get(ticker, self.positions[ticker]['entry_price'])
            for ticker in self.positions
        )
        return self.cash + position_value

    def print_summary(self):
        """打印持仓汇总"""
        print(f"\n{'='*70}")
        print("持仓管理器状态")
        print(f"{'='*70}")
        print(f"初始资金: ${self.initial_capital:.2f}")
        print(f"当前现金: ${self.cash:.2f}")
        print(f"持仓数量: {len(self.positions)}/{self.max_positions}")

        if self.positions:
            print(f"\n当前持仓:")
            for ticker, pos in self.positions.items():
                cost = pos['cost']
                print(f"  {ticker}: {pos['shares']}股 @ ${pos['entry_price']:.4f} (Day {pos['entry_day']}, 成本${cost:.2f})")

        if self.history:
            total_trades = len([h for h in self.history if h['action'] == 'SELL'])
            winning_trades = len([h for h in self.history if h['action'] == 'SELL' and h['pnl'] > 0])
            total_pnl = sum(h.get('pnl', 0) for h in self.history if h['action'] == 'SELL')

            print(f"\n交易统计:")
            print(f"  完成交易: {total_trades}")
            print(f"  盈利交易: {winning_trades} ({winning_trades/total_trades*100:.1f}% 胜率)" if total_trades > 0 else "  完成交易: 0")
            print(f"  总盈亏: ${total_pnl:+.2f}")

        print(f"{'='*70}\n")

    def save_history(self, filepath='data/position_history.csv'):
        """保存交易历史到CSV"""
        if self.history:
            df = pd.DataFrame(self.history)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            df.to_csv(filepath, index=False)
            print(f"[持仓管理] 交易历史已保存: {filepath}")
