# -*- coding: utf-8 -*-
"""V1 三版本压力测试
测试1: 手续费提高 (0.08% -> 0.15%, 0.25%)
测试2: 延迟成交 (信号后1根4H开盘成交, 模拟人工确认)
测试3: 分阶段 (训练期2023-2024 vs 验证期2025)
"""
import os, sys, json, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
from pools import load_all_available, fixed_pool, dynamic_pool, hybrid_pool
from v1_engine import V1Backtest
from metrics import compute_metrics

START = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
MID = int(datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
END = int(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
INITIAL = 10000
BARS_PER_DAY = 6

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

def make_provider(all_coins, mode, start_ts):
    fixed_base = [c for c in fixed_pool(all_coins)]
    cache = {}
    def provider(bi, ts, current_pool):
        day_key = ts // (24 * 3600 * 1000)
        if day_key in cache:
            return cache[day_key]
        if mode == 'fixed':
            pool = fixed_base
        elif mode == 'dynamic':
            pool = dynamic_pool(all_coins, ts, top_n=33)
            if pool is None or len(pool) < 20:
                pool = fixed_base
        else:
            pool = hybrid_pool(all_coins, ts, fixed_base, top_n=33)
            if pool is None or len(pool) < 20:
                pool = fixed_base
        cache[day_key] = pool
        return pool
    return provider

def run_one(all_coins, mode, s, e, fees=0.0005, slippage=0.0003, delay=0):
    bt = V1Backtest(
        coins_data=all_coins, start_ts=s, end_ts=e, initial=INITIAL,
        pool_provider=make_provider(all_coins, mode, s),
        pool_update_bars=BARS_PER_DAY, fees=fees, slippage=slippage, delay_bars=delay,
    )
    r = bt.run()
    bt.close_all()
    m = compute_metrics(bt.equity, bt.trades, s, e, INITIAL)
    return m

def main():
    all_coins = load_all_available()
    modes = ['fixed', 'dynamic', 'hybrid']
    labels = {'fixed': '固定33', 'dynamic': 'Dynamic', 'hybrid': 'Hybrid'}

    results = {}

    # 基准 (原始费用0.08%, 无延迟)
    print('\n========== 基准 (费用0.08%, 无延迟) ==========')
    for mode in modes:
        m = run_one(all_coins, mode, START, END)
        results[f'base_{mode}'] = m
        print(f"  {labels[mode]:8s}: 收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% 交易{m['trades']}")

    # 测试1: 手续费提高
    print('\n========== 测试1: 手续费提高 0.15% ==========')
    for mode in modes:
        m = run_one(all_coins, mode, START, END, fees=0.00075, slippage=0.00075)
        results[f'fee15_{mode}'] = m
        print(f"  {labels[mode]:8s}: 收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}%")
    print('\n========== 测试1b: 手续费提高 0.25% ==========')
    for mode in modes:
        m = run_one(all_coins, mode, START, END, fees=0.00125, slippage=0.00125)
        results[f'fee25_{mode}'] = m
        print(f"  {labels[mode]:8s}: 收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}%")

    # 测试2: 延迟成交 1根4H
    print('\n========== 测试2: 延迟1根4H成交 ==========')
    for mode in modes:
        m = run_one(all_coins, mode, START, END, delay=1)
        results[f'delay_{mode}'] = m
        print(f"  {labels[mode]:8s}: 收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% 交易{m['trades']}")

    # 测试3: 分阶段
    print('\n========== 测试3: 训练期 2023-2024 ==========')
    for mode in modes:
        m = run_one(all_coins, mode, START, MID)
        results[f'train_{mode}'] = m
        print(f"  {labels[mode]:8s}: 收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% 交易{m['trades']}")
    print('\n========== 测试3b: 验证期 2025 ==========')
    for mode in modes:
        m = run_one(all_coins, mode, MID, END)
        results[f'test_{mode}'] = m
        print(f"  {labels[mode]:8s}: 收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% 交易{m['trades']}")

    with open(os.path.join(RESULTS_DIR, 'stress_test_results.json'), 'w') as f:
        json.dump(results, f, default=str, indent=2)
    print('\n压力测试结果已保存: results/stress_test_results.json')

if __name__ == '__main__':
    main()
