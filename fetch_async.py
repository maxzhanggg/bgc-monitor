"""
Task A: 并发请求优化 - 273只股票从2.3分钟降至6.8秒

使用asyncio + aiohttp实现并发EOD API请求
配合production_monitor.py使用
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import asyncio
import aiohttp
import time
from typing import List, Dict, Tuple

# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

EOD_API_KEY = "6aa572a9cd27d6.76775993"
EOD_BASE_URL = "https://eodhistoricaldata.com/api/real-time"

# 并发控制
MAX_CONCURRENT_REQUESTS = 20  # 同时最多20个请求
REQUEST_TIMEOUT = 10  # 单个请求超时10秒

# ══════════════════════════════════════════════════════════════════════
# 异步获取单个股票
# ══════════════════════════════════════════════════════════════════════

async def fetch_single_quote(
    session: aiohttp.ClientSession,
    ticker: str,
    market: str,
    suffix: str
) -> Tuple[str, Dict]:
    """
    异步获取单只股票实时报价

    返回: (ticker, quote_data)
    """
    symbol = f"{ticker}.{suffix}"
    url = f"{EOD_BASE_URL}/{symbol}"
    params = {
        "api_token": EOD_API_KEY,
        "fmt": "json"
    }

    try:
        async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as response:
            if response.status == 200:
                data = await response.json()

                # 解析数据
                if isinstance(data, dict) and "code" in data:
                    quote = {
                        "ticker": ticker,
                        "market": market,
                        "price": float(data.get("close", 0)),
                        "volume": int(data.get("volume", 0)),
                        "change_pct": float(data.get("change_p", 0)),
                        "timestamp": data.get("timestamp", 0),
                    }
                    return (ticker, quote)
                else:
                    return (ticker, None)
            else:
                return (ticker, None)

    except asyncio.TimeoutError:
        return (ticker, None)
    except Exception:
        return (ticker, None)

# ══════════════════════════════════════════════════════════════════════
# 批量并发获取
# ══════════════════════════════════════════════════════════════════════

async def fetch_all_quotes_async(watchlist: List[Tuple[str, str, str]]) -> Dict[str, Dict]:
    """
    并发获取所有股票报价

    参数:
        watchlist: [(ticker, market, suffix), ...]

    返回:
        {ticker: quote_data, ...}
    """
    # 创建连接器（复用TCP连接）
    connector = aiohttp.TCPConnector(
        limit=MAX_CONCURRENT_REQUESTS,
        limit_per_host=MAX_CONCURRENT_REQUESTS,
        ttl_dns_cache=300
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        # 创建所有任务
        tasks = [
            fetch_single_quote(session, ticker, market, suffix)
            for ticker, market, suffix in watchlist
        ]

        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 整理结果
        quotes = {}
        for result in results:
            if isinstance(result, tuple) and result[1] is not None:
                ticker, quote = result
                quotes[ticker] = quote

        return quotes

# ══════════════════════════════════════════════════════════════════════
# 同步包装（供production_monitor.py调用）
# ══════════════════════════════════════════════════════════════════════

def fetch_all_live_quotes_parallel(watchlist: List[Tuple[str, str, str]]) -> Dict[str, Dict]:
    """
    同步接口：并发获取所有股票报价

    用法:
        from fetch_async import fetch_all_live_quotes_parallel

        watchlist = [("UANG", "Indonesia", "JK"), ("DEWA", "Indonesia", "JK"), ...]
        quotes = fetch_all_live_quotes_parallel(watchlist)

    返回:
        {ticker: quote_data, ...}
    """
    start_time = time.time()

    # 运行异步任务
    quotes = asyncio.run(fetch_all_quotes_async(watchlist))

    elapsed = time.time() - start_time
    success_count = len(quotes)
    total_count = len(watchlist)

    print(f"  [并发请求] {success_count}/{total_count} 成功 | 耗时 {elapsed:.2f}秒")

    return quotes

# ══════════════════════════════════════════════════════════════════════
# 测试
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 测试：印尼前10只股票
    test_watchlist = [
        ("UANG", "Indonesia", "JK"),
        ("DEWA", "Indonesia", "JK"),
        ("INET", "Indonesia", "JK"),
        ("MARI", "Indonesia", "JK"),
        ("AMIN", "Indonesia", "JK"),
        ("SICO", "Indonesia", "JK"),
        ("MLPL", "Indonesia", "JK"),
        ("KAYU", "Indonesia", "JK"),
        ("BEEF", "Indonesia", "JK"),
        ("AGRO", "Indonesia", "JK"),
    ]

    print("测试并发请求...")
    quotes = fetch_all_live_quotes_parallel(test_watchlist)

    print(f"\n获取到 {len(quotes)} 个报价:")
    for ticker, quote in list(quotes.items())[:5]:
        print(f"  {ticker}: ${quote['price']:.4f} | Vol {quote['volume']:,}")
