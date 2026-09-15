"""
后台自动数据采集脚本
每天定时运行，无需Web界面

运行方式：
1. Windows任务计划：每天09:00执行
2. 或者：python auto_collector.py（24小时常驻）
"""

import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import time
import logging

# 配置
WATCHLIST_CSV = 'data/processed/watchlist_final.csv'
DATA_STORAGE_DIR = 'data/daily_snapshots'
EOD_API_KEY = '6aa572a9cd27d6.76775993'  # EOD Historical Data API Key
EOD_BASE_URL = 'https://eodhistoricaldata.com/api/eod'
TRADING_CALENDAR_JSON = 'trading_calendar.json'

# 日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/auto_collector.log'),
        logging.StreamHandler()
    ]
)

class AutoDataCollector:
    """自动数据采集器"""

    def __init__(self):
        self.watchlist = pd.read_csv(WATCHLIST_CSV)
        self.storage_dir = Path(DATA_STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # 加载交易日历
        with open(TRADING_CALENDAR_JSON, 'r', encoding='utf-8') as f:
            self.calendar = json.load(f)

        logging.info(f"初始化采集器: {len(self.watchlist)} 只股票")

    def is_trading_day(self, date):
        """
        判断是否为交易日

        参数:
            date: datetime对象
        返回:
            bool: True=交易日, False=休市
        """
        # 周末
        if date.weekday() in self.calendar['weekends']:
            return False

        date_str = date.strftime('%Y-%m-%d')

        # 印尼或泰国任一市场开市即为交易日
        indonesia_holiday = date_str in self.calendar['market_holidays']['Indonesia']
        thailand_holiday = date_str in self.calendar['market_holidays']['Thailand']

        # 两个市场都休市才算休市
        return not (indonesia_holiday and thailand_holiday)

    def fetch_eod_data(self, eod_code, date):
        """
        从EOD HD获取单只股票数据

        参数:
            eod_code: 如 "BBCA.JK"
            date: datetime对象
        """
        url = f"{EOD_BASE_URL}/{eod_code}"
        params = {
            'api_token': EOD_API_KEY,
            'from': date.strftime('%Y-%m-%d'),
            'to': date.strftime('%Y-%m-%d'),
            'fmt': 'json'
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if len(data) > 0:
                return data[0]  # 返回当日数据
            else:
                return None

        except Exception as e:
            logging.error(f"获取 {eod_code} 失败: {e}")
            return None

    def collect_date(self, target_date):
        """
        采集指定日期的数据

        参数:
            target_date: datetime对象
        """
        date_str = target_date.strftime('%Y%m%d')
        date_dir = self.storage_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        logging.info(f"开始采集 {date_str} 数据...")

        success_count = 0
        fail_count = 0

        for idx, row in self.watchlist.iterrows():
            ticker = row['ticker']
            eod_code = row['eod_code']

            # 检查是否已存在
            output_file = date_dir / f"{ticker}.csv"
            if output_file.exists():
                logging.debug(f"跳过 {ticker} (已存在)")
                success_count += 1
                continue

            # 获取数据
            data = self.fetch_eod_data(eod_code, target_date)

            if data:
                # 保存为CSV
                df = pd.DataFrame([{
                    'date': data['date'],
                    'open': data['open'],
                    'high': data['high'],
                    'low': data['low'],
                    'close': data['close'],
                    'adjusted_close': data['adjusted_close'],
                    'volume': data['volume'],
                    'ticker': ticker,
                    'market': row['market']
                }])
                df.to_csv(output_file, index=False)
                success_count += 1
                logging.info(f"✓ {ticker} ({success_count}/{len(self.watchlist)})")
            else:
                fail_count += 1
                logging.warning(f"✗ {ticker} 无数据")

            # 避免API限速
            time.sleep(0.1)

        logging.info(f"采集完成: 成功 {success_count}, 失败 {fail_count}")
        return success_count, fail_count

    def run_daily_collection(self):
        """每日自动采集（采集前一个交易日）"""
        # 采集前一天的数据（EOD通常T+1才有完整数据）
        target_date = datetime.now() - timedelta(days=1)

        # 往回找到最近的交易日
        while not self.is_trading_day(target_date):
            target_date -= timedelta(days=1)
            logging.info(f"跳过非交易日，回退到 {target_date.strftime('%Y-%m-%d')}")

        success, fail = self.collect_date(target_date)

        # 记录采集状态
        status_file = self.storage_dir / 'collection_status.json'
        status = {
            'last_run': datetime.now().isoformat(),
            'target_date': target_date.strftime('%Y-%m-%d'),
            'success': success,
            'fail': fail,
            'total': len(self.watchlist)
        }

        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2)

        return success, fail

    def run_forever(self):
        """24小时常驻，每天09:00自动采集"""
        logging.info("启动24小时常驻模式")

        while True:
            now = datetime.now()

            # 每天09:00执行
            if now.hour == 9 and now.minute == 0:
                logging.info("触发定时采集...")
                try:
                    self.run_daily_collection()
                except Exception as e:
                    logging.error(f"采集失败: {e}")

                # 休眠1小时，避免重复触发
                time.sleep(3600)
            else:
                # 每分钟检查一次
                time.sleep(60)

def main():
    """主函数"""
    collector = AutoDataCollector()

    # 模式选择
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        # 单次采集模式
        logging.info("单次采集模式")
        collector.run_daily_collection()
    else:
        # 24小时常驻模式
        collector.run_forever()

if __name__ == '__main__':
    main()
