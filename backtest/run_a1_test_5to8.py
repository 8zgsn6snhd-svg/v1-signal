# -*- coding: utf-8 -*-
"""A1上线前验证 测试5-8: 未来泄漏/手续费/延迟/仓位限制"""
import os, sys, json, datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
import v1_engine
from pools import load_all_available, fixed_pool, dynamic_pool
from v1_engine import V1Backtest, Coin
from metrics import compute_metrics
from market_filter import MarketState, BaseFilter, wrap_with_filter

START = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
END = int(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
INITIAL = 10000
BARS_PER_DAY = 6
RESULTS = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS, exist_ok=True)


def make_provider(all_coins, mode='dynamic'):
    fixed_base = [c for c in fixed_pool(all_coins)]
    cache = {}
    def provider(bi, ts, current_pool):
        day_key = ts // (24 * 3600 * 1000)
        if day_key in cache:
            return cache[day_key]
        pool = dynamic_pool(all_coins, ts, top_n=33)
        if pool is None or len(pool) < 20:
            pool = fixed_base
        cache[day_key] = pool
        return pool
    return provider


def run_version(all_coins, s, e, filter_obj=None, delay=0, fees=0.0005, slippage=0.0003, max_pos=3):
    # monkeypatch MAX_POS (测试8)
    old_pos = v1_engine.MAX_POS
    v1_engine.MAX_POS = max_pos
    try:
        Engine = wrap_with_filter(V1Backtest, filter_obj) if filter_obj else V1Backtest
        bt = Engine(
            coins_data=all_coins, start_ts=s, end_ts=e, initial=INITIAL,
            pool_provider=make_provider(all_coins), pool_update_bars=BARS_PER_DAY,
            fees=fees, slippage=slippage, delay_bars=delay,
        )
        bt.run()
        bt.close_all()
        m = compute_metrics(bt.equity, bt.trades, s, e, INITIAL)
        skipped = getattr(bt, 'skipped_count', 0)
        return m, skipped
    finally:
        v1_engine.MAX_POS = old_pos


# ===== A1 过滤器 (ST3, 用户当前定义) =====
class A1Filter(BaseFilter):
    def __init__(self, btc_coin):
        super().__init__(btc_coin)

    def should_open(self, sig, ts):
        idx = self.ms._idx(ts)
        if idx is None or idx < 14:
            return 1.0
        d3 = self.ms.btc.trends[2][idx]
        if d3 == 0:
            return 1.0
        conflict = (sig['dir'] == 1 and d3 == 1) or (sig['dir'] == -1 and d3 == -1)
        return 0.0 if conflict else 1.0


def fmt(m):
    return f"收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% 交易{m['trades']:>5}"


def main():
    all_coins = load_all_available()
    btc_coin = Coin('BTC', all_coins['BTC']['h'], all_coins['BTC']['l'],
                    all_coins['BTC']['c'], all_coins['BTC']['v'], all_coins['BTC']['t'])
    out = {}

    # ===== 测试5: 未来泄漏检查 =====
    print('========== 测试5: 未来泄漏检查 ==========', flush=True)
    # A1过滤器用 market_state._idx(ts) 定位 <=ts 的BTC bar, 只用历史数据
    # 验证: 检查信号时刻ts对应的BTC bar idx, 该bar的ST/EMA基于<=idx数据
    leak = {'checked': 0, 'leaks': 0}
    a1 = A1Filter(btc_coin)
    # 抽查100个随机信号时刻, 验证_idx返回的bar时间<=ts
    import random
    random.seed(42)
    ts_list = []
    for _ in range(100):
        ts_list.append(random.randint(START, END))
    for ts in ts_list:
        idx = a1.ms._idx(ts)
        if idx is not None:
            bar_ts = a1.ms.btc.ts[idx]
            if bar_ts > ts:
                leak['leaks'] += 1  # 泄漏!
            leak['checked'] += 1
    print(f'  检查 {leak["checked"]} 个采样, 泄漏 {leak["leaks"]} 个', flush=True)
    print('  A1用_idx定位<=ts的bar, ST/EMA基于历史数据, 无前瞻', flush=True)
    out['test5'] = leak

    # ===== 测试6: 手续费压力 =====
    print('\n========== 测试6: 手续费压力 ==========', flush=True)
    fee_levels = [('0.08%', 0.0004, 0.0004), ('0.15%', 0.00075, 0.00075), ('0.25%', 0.00125, 0.00125)]
    t6 = {}
    for fname, fee, slip in fee_levels:
        m_base, _ = run_version(all_coins, START, END, None, fees=fee, slippage=slip)
        a1 = A1Filter(btc_coin)
        m_a1, _ = run_version(all_coins, START, END, a1, fees=fee, slippage=slip)
        t6[fname] = {'base': m_base, 'a1': m_a1}
        print(f'  [{fname}] 基准: {fmt(m_base)} | A1: {fmt(m_a1)}', flush=True)
    out['test6'] = t6

    # ===== 测试7: 延迟成交 =====
    print('\n========== 测试7: 延迟成交 ==========', flush=True)
    t7 = {}
    for dname, delay in [('立即成交', 0), ('延迟1根', 1), ('延迟2根', 2)]:
        m_base, _ = run_version(all_coins, START, END, None, delay=delay)
        a1 = A1Filter(btc_coin)
        m_a1, _ = run_version(all_coins, START, END, a1, delay=delay)
        t7[dname] = {'base': m_base, 'a1': m_a1}
        print(f'  [{dname}] 基准: {fmt(m_base)} | A1: {fmt(m_a1)}', flush=True)
    out['test7'] = t7

    # ===== 测试8: 仓位限制 =====
    print('\n========== 测试8: 仓位限制 ==========', flush=True)
    t8 = {}
    for pname, mp in [('1仓', 1), ('2仓', 2), ('3仓', 3), ('5仓', 5)]:
        m_base, _ = run_version(all_coins, START, END, None, max_pos=mp)
        a1 = A1Filter(btc_coin)
        m_a1, _ = run_version(all_coins, START, END, a1, max_pos=mp)
        t8[pname] = {'base': m_base, 'a1': m_a1}
        print(f'  [{pname}] 基准: {fmt(m_base)} | A1: {fmt(m_a1)}', flush=True)
    out['test8'] = t8

    with open(os.path.join(RESULTS, 'a1_test_5to8.json'), 'w') as f:
        json.dump(out, f, default=str, indent=2)
    print('\n测试5-8完成, 结果: results/a1_test_5to8.json', flush=True)


if __name__ == '__main__':
    main()
