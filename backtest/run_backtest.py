# -*- coding: utf-8 -*-
"""V1 三版本对比回测主脚本

版本A: 固定33币 (生产池)
版本B: 动态33币 (全市场->上市>1年->成交量过滤->流动性Top33, 每天重选)
版本C: Hybrid (固定基础池 + 90天弱币检测替换为强势币, 每周重估)

统一: 同时间窗 2023-01-01 ~ 2026-01-01, 同资金10000U, 同V1引擎
只改变: 币池生成方式
"""
import os, sys, pickle, json, datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
from pools import (load_all_available, fixed_pool, dynamic_pool, hybrid_pool)
from v1_engine import V1Backtest
from metrics import compute_metrics

START_TS = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
END_TS = int(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
INITIAL = 10000
BARS_PER_DAY = 6  # 4H bar, 每天6根

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

def run_version(name, all_coins, pool_mode):
    """pool_mode: 'fixed' | 'dynamic' | 'hybrid'"""
    print(f'\n===== 运行版本: {name} ({pool_mode}) =====', flush=True)
    t0 = time.time()

    # 构建滚动池 provider
    def make_provider(mode):
        cache = {}
        def provider(bi, ts, current_pool):
            # 每天重新评估池子
            day_key = ts // (24 * 3600 * 1000)
            if day_key in cache:
                return cache[day_key]
            if mode == 'fixed':
                pool = fixed_pool(all_coins)
            elif mode == 'dynamic':
                pool = dynamic_pool(all_coins, ts, top_n=33)
            else:
                base = fixed_pool(all_coins)
                pool = hybrid_pool(all_coins, ts, base, top_n=33)
            cache[day_key] = pool
            return pool
        return provider

    bt = V1Backtest(
        coins_data=all_coins,
        start_ts=START_TS, end_ts=END_TS, initial=INITIAL,
        pool_provider=make_provider(pool_mode),
        pool_update_bars=BARS_PER_DAY,
    )
    result = bt.run()
    bt.close_all()
    # 最后权益
    final_eq = bt.balance
    if bt.positions:
        pass  # close_all 已把持仓平掉, balance已更新
    # 重新取完整equity(含close_all后)
    eq_final = bt.equity[-1][1] if bt.equity else final_eq

    metrics = compute_metrics(bt.equity, bt.trades, START_TS, END_TS, INITIAL)
    print(f'  完成 {time.time()-t0:.0f}s, {metrics["trades"]}笔交易', flush=True)
    return {'name': name, 'mode': pool_mode, 'metrics': metrics, 'trades': bt.trades}

def main():
    print('加载数据...', flush=True)
    all_coins = load_all_available()
    print(f'可用币: {len(all_coins)}', flush=True)

    versions = [
        ('V1.3-固定33', 'fixed'),
        ('V1-Dynamic', 'dynamic'),
        ('V1-Hybrid', 'hybrid'),
    ]
    results = {}
    for name, mode in versions:
        res = run_version(name, all_coins, mode)
        results[name] = res

    # 保存结果
    with open(os.path.join(RESULTS_DIR, 'comparison_results.json'), 'w') as f:
        json.dump({k: {**v, 'trades': v['trades']} for k, v in results.items()},
                  f, default=str, indent=2)

    # 汇总打印
    print('\n\n========== 对比汇总 ==========')
    header = f"{'版本':<16} {'总收益':>8} {'年化':>8} {'回撤':>7} {'PF':>6} {'交易数':>6} {'胜率':>6} {'连亏':>4} {'平均R':>6}"
    print(header)
    print('-' * len(header))
    for name, res in results.items():
        m = res['metrics']
        print(f"{name:<16} {m['total_ret']:>+7.1f}% {m['annual']:>+7.1f}% "
              f"{m['max_dd']:>6.1f}% {m['pf']:>6.2f} {m['trades']:>6} "
              f"{m['win_rate']:>5.1f}% {m['max_consec_loss']:>4} {m['avg_R']:>6.2f}")

    # 分年份
    print('\n---- 分年份表现 (P&L) ----')
    for name, res in results.items():
        yearly = res['metrics']['yearly']
        ys = sorted(yearly.keys())
        line = f"{name:<16}"
        for y in ys:
            line += f" {y}: {yearly[y]['pnl']:>+12.0f} ({yearly[y]['n']}笔)"
        print(line)

if __name__ == '__main__':
    main()
