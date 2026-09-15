# -*- coding: utf-8 -*-
"""验证新的仓位分配逻辑"""

ALLOCATION_BY_TIER = {
    1: 200_000,
    2: 150_000,
    3: 120_000,
    4: 80_000,
}

LIQUIDITY_LIMITS = {
    'L0': 60_000,
    'L1': 80_000,
    'L2': 120_000,
    'L3': 200_000,
}

MAX_COUNTRY_EXPOSURE_48H = 250_000

print("=" * 60)
print("仓位分配验证")
print("=" * 60)

print("\n【1】单个信号最大仓位 = min(tier_allocation, liquidity_limit):\n")
for tier in [1, 2, 3, 4]:
    print(f"  S{tier}信号:")
    for liq in ['L0', 'L1', 'L2', 'L3']:
        alloc = min(ALLOCATION_BY_TIER[tier], LIQUIDITY_LIMITS[liq])
        print(f"    {liq}流动性: ${alloc:,}")
    print()

print("\n【2】验证比赛规则: 单笔持仓 ≤ $200,000")
max_single = max(
    min(ALLOCATION_BY_TIER[t], LIQUIDITY_LIMITS[l])
    for t in [1, 2, 3, 4]
    for l in ['L0', 'L1', 'L2', 'L3']
)
status = "[PASS]" if max_single <= 200_000 else "[FAIL]"
print(f"  最大单笔仓位: ${max_single:,} {status}")

print("\n【3】国家暴露上限 (MAX_COUNTRY_EXPOSURE_48H):")
print(f"  值: ${MAX_COUNTRY_EXPOSURE_48H:,}")
print("\n  含义:")
print("  - 过去48小时内，对同一个国家(IDX或SET)的")
print("    所有新开仓位allocation之和 ≤ $250,000")
print("\n  示例:")
print("  - 如果48小时内已有IDX股票累计开仓$200,000")
print("  - 新的IDX信号最多只能再开$50,000")
print("  - 此时如果来了S1信号(tier allocation $200k)")
print("  - 实际开仓会被限制为$50,000")
print("\n  代码位置:")
print("  - production_monitor.py 第730-750行")
print("  - check_country_exposure() 函数")
print("=" * 60)
