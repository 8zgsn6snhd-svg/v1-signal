# -*- coding: utf-8 -*-
"""震荡趋势过滤专项回测 — 不改引擎核心

基准: V1 Dynamic 无过滤
方案A: BTC趋势一致过滤 (ban/half)
方案B: BTC ST状态过滤 (ban/half)
方案C: ATR震荡过滤 (ban/half)
方案D: ADX趋势强度过滤 (ban/half)
方案E: 综合市场状态评分

统一: 2023-01-01~2026-01-01, 10000U, V1策略不变
"""
import os, sys, json, datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
from pools import load_all_available, fixed_pool, dynamic_pool
from v1_engine import V1Backtest
from metrics import compute_metrics
from market_filter import make_filter, wrap_with_filter

START = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
END = int(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
INITIAL = 10000
BARS_PER_DAY = 6

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)


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


def run_version(all_coins, name, filter_obj=None):
    """运行回测, filter_obj: Filter对象 or None"""
    Engine = wrap_with_filter(V1Backtest, filter_obj) if filter_obj else V1Backtest
    bt = Engine(
        coins_data=all_coins, start_ts=START, end_ts=END, initial=INITIAL,
        pool_provider=make_provider(all_coins), pool_update_bars=BARS_PER_DAY,
    )
    bt.run()
    bt.close_all()
    m = compute_metrics(bt.equity, bt.trades, START, END, INITIAL)
    skipped = getattr(bt, 'skipped_count', 0)
    return m, skipped


def main():
    all_coins = load_all_available()
    print(f'可用币: {len(all_coins)}')

    # BTC coin (市场状态基准)
    btc_coin = None
    if 'BTC' in all_coins:
        # 用Coin包装
        from v1_engine import Coin
        d = all_coins['BTC']
        btc_coin = Coin('BTC', d['h'], d['l'], d['c'], d['v'], d['t'])
    else:
        print('WARNING: 无BTC数据')
        return

    # 方案定义: 含新方案F/G/H/I/J/K
    schemes = [
        # (name, scheme, variant, params)
        ('基准-Dynamic', None, None, None),
        # 上次最优
        ('A1-BTC趋势禁反向', 'a', 'ban', None),
        # 新方案
        ('F-山寨趋势确认', 'f', None, None),
        ('G-同币止损冷却24', 'g', None, {'cooldown_bars': 24}),
        ('H-BTC趋势持续6', 'h', None, {'n_bars': 6}),
        ('I-山寨自身ATR', 'i', None, None),
        ('J-BTC+ADX分级', 'j', None, None),
        ('K-每日新仓上限2', 'k', None, {'max_daily': 2}),
    ]

    results = {}
    print('\n========== 回测运行 ==========', flush=True)
    for name, scheme, variant, params in schemes:
        t0 = time.time()
        if scheme is None:
            filter_obj = None
        else:
            filter_obj = make_filter(scheme, variant, btc_coin, all_coins, params)
        m, skipped = run_version(all_coins, name, filter_obj)
        results[name] = {
            'scheme': scheme, 'variant': variant, 'metrics': m, 'skipped': skipped
        }
        print(f'  {name}: 收益{m["total_ret"]:+.1f}% PF{m["pf"]:.2f} '
              f'回撤{m["max_dd"]:.1f}% 交易{m["trades"]} 跳过{skipped} '
              f'({time.time()-t0:.0f}s)', flush=True)

    # 保存
    with open(os.path.join(RESULTS_DIR, 'market_filter_results.json'), 'w') as f:
        json.dump(results, f, default=str, indent=2)

    # 汇总表
    print('\n\n========== 对比汇总 ==========')
    header = f"{'方案':<22} {'收益':>9} {'年化':>9} {'回撤':>7} {'PF':>6} {'交易':>5} {'胜率':>6} {'连亏':>4} {'跳过':>5}"
    print(header)
    print('-' * len(header))
    base = results['基准-Dynamic']['metrics']
    for name, r in results.items():
        m = r['metrics']
        diff = ''
        if name != '基准-Dynamic':
            ret_diff = m['total_ret'] - base['total_ret']
            dd_diff = m['max_dd'] - base['max_dd']
            pf_diff = m['pf'] - base['pf']
            diff = f' Δ收益{ret_diff:+.0f}% ΔPF{pf_diff:+.2f} Δ回撤{dd_diff:+.1f}%'
        print(f"{name:<22} {m['total_ret']:>+8.1f}% {m['annual']:>+8.1f}% "
              f"{m['max_dd']:>6.1f}% {m['pf']:>6.2f} {m['trades']:>5} "
              f"{m['win_rate']:>5.1f}% {m['max_consec_loss']:>4} {r['skipped']:>5}{diff}")

    print('\n结果已保存: results/market_filter_results.json')


if __name__ == '__main__':
    main()
