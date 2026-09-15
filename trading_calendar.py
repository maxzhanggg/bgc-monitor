"""
交易日历 - 印尼/泰国 2026年10月-11月
修复竞赛日计算错误（使用交易日而非日历日）
"""

from datetime import datetime, timedelta

# 比赛时间
COMPETITION_START = datetime(2026, 10, 13)
COMPETITION_END = datetime(2026, 11, 14)

# 印尼假期（IDX）
INDONESIA_HOLIDAYS_2026 = [
    datetime(2026, 10, 28),  # 印尼假期
    datetime(2026, 11, 10),  # 印尼假期
]

# 泰国假期（SET）
THAILAND_HOLIDAYS_2026 = [
    datetime(2026, 10, 23),  # 泰国假期
]

def get_trading_days(start_date, end_date, market='Indonesia'):
    """
    计算交易日列表（排除周末和假期）

    Args:
        start_date: 起始日期
        end_date: 结束日期
        market: 'Indonesia' or 'Thailand'

    Returns:
        list of datetime: 交易日列表
    """
    holidays = INDONESIA_HOLIDAYS_2026 if market == 'Indonesia' else THAILAND_HOLIDAYS_2026

    trading_days = []
    current = start_date

    while current <= end_date:
        # 跳过周末（周六=5，周日=6）
        # 跳过假期
        if current.weekday() < 5 and current not in holidays:
            trading_days.append(current)

        current += timedelta(days=1)

    return trading_days

def calculate_competition_day(current_date, market='Indonesia'):
    """
    计算当前是比赛第几个交易日

    Args:
        current_date: datetime or date object
        market: 'Indonesia' or 'Thailand'

    Returns:
        int: 竞赛交易日编号（1-based）
    """
    # 确保是datetime对象
    if not isinstance(current_date, datetime):
        current_date = datetime.combine(current_date, datetime.min.time())

    # 如果在比赛前
    if current_date < COMPETITION_START:
        return 0

    # 如果在比赛后
    if current_date > COMPETITION_END:
        return -1

    # 计算从比赛开始到当前日期的交易日数
    trading_days = get_trading_days(COMPETITION_START, current_date, market)

    return len(trading_days)

def get_days_remaining(current_date, market='Indonesia'):
    """
    计算剩余交易日数量

    Args:
        current_date: datetime or date object
        market: 'Indonesia' or 'Thailand'

    Returns:
        int: 剩余交易日数量
    """
    if not isinstance(current_date, datetime):
        current_date = datetime.combine(current_date, datetime.min.time())

    if current_date >= COMPETITION_END:
        return 0

    remaining_days = get_trading_days(current_date, COMPETITION_END, market)

    return len(remaining_days)

def is_trading_day(date, market='Indonesia'):
    """
    判断某日是否为交易日

    Args:
        date: datetime or date object
        market: 'Indonesia' or 'Thailand'

    Returns:
        bool: True if trading day, False otherwise
    """
    if not isinstance(date, datetime):
        date = datetime.combine(date, datetime.min.time())

    holidays = INDONESIA_HOLIDAYS_2026 if market == 'Indonesia' else THAILAND_HOLIDAYS_2026

    # 周末或假期
    if date.weekday() >= 5 or date in holidays:
        return False

    return True

if __name__ == '__main__':
    # 测试
    print("=" * 70)
    print("交易日历测试")
    print("=" * 70)

    test_dates = [
        datetime(2026, 10, 13),  # Day 1
        datetime(2026, 10, 18),  # 周六
        datetime(2026, 10, 20),  # 周一
        datetime(2026, 10, 23),  # 泰国假期
        datetime(2026, 10, 28),  # 印尼假期
        datetime(2026, 11, 10),  # 印尼假期
        datetime(2026, 11, 14),  # 最后一天
    ]

    for date in test_dates:
        indo_day = calculate_competition_day(date, 'Indonesia')
        thai_day = calculate_competition_day(date, 'Thailand')

        print(f"\n{date.strftime('%Y-%m-%d (%A)')}")
        print(f"  印尼: Day {indo_day}, 交易日={is_trading_day(date, 'Indonesia')}")
        print(f"  泰国: Day {thai_day}, 交易日={is_trading_day(date, 'Thailand')}")

    # 计算总交易日数
    indo_total = len(get_trading_days(COMPETITION_START, COMPETITION_END, 'Indonesia'))
    thai_total = len(get_trading_days(COMPETITION_START, COMPETITION_END, 'Thailand'))

    print(f"\n{'='*70}")
    print(f"比赛总交易日:")
    print(f"  印尼: {indo_total} 天")
    print(f"  泰国: {thai_total} 天")
    print(f"{'='*70}")
