# -*- coding: utf-8 -*-
"""BTC趋势过滤风险调整方案测试
不一致降仓(而非禁止): C-half(50%)/C-70(降30%)/C-30(降70%)
一致: 正常仓位
"""
import os, sys, json, datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
import v1_engine
from pools import load_all_available, fixed_pool, dynamic_pool
from v1_engine import V1Backtest, Coin
from metrics import compute_metrics
from market_filter import BaseFilter, wrap_with_filter

START = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
MID = int(datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
MID2 = int(datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
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


def run_version(all_coins, s, e, filter_obj=None):
    Engine = wrap_with_filter(V1Backtest, filter_obj) if filter_obj else V1Backtest
    bt = Engine(
        coins_data=all_coins, start_ts=s, end_ts=e, initial=INITIAL,
        pool_provider=make_provider(all_coins), pool_update_bars=BARS_PER_DAY,
    )
    bt.run()
    bt.close_all()
    m = compute_metrics(bt.equity, bt.trades, s, e, INITIAL)
    return m


class CAdjustFilter(BaseFilter):
    """BTC ST2/ST3: 不一致降仓(乘数), 一致正常
    reduce: 不一致时仓位乘数 (0.5/0.7/0.3)"""
    def __init__(self, btc_coin, reduce):
        super().__init__(btc_coin)
        self.reduce = reduce

    def _st_dirs(self, ts):
        idx = self.ms._idx(ts)
        if idx is None:
            return None, None
        d2 = self.ms.btc.trends[1][idx] if idx >= 10 else 0
        d3 = self.ms.btc.trends[2][idx] if idx >= 14 else 0
        return d2, d3

    def should_open(self, sig, ts):
        d2, d3 = self._st_dirs(ts)
        if d2 == 0 or d3 == 0:
            return self.reduce  # 数据不足, 保守降仓
        if d2 != d3:
            return self.reduce  # 不一致: 降仓
        # 一致: 顺势正常, 逆势也正常(不过滤方向, 只调风险)
        return 1.0


def fmt(m):
    return (f"收益{m['total_ret']:>+8.1f}% 年化{m['annual']:>+7.1f}% 回撤{m['max_dd']:>5.1f}% "
            f"PF{m['pf']:>6.2f} 交易{m['trades']:>5} 胜率{m['win_rate']:>5.1f}% 连亏{m['max_consec_loss']:>3}")


def main():
    all_coins = load_all_available()
    btc_coin = Coin('BTC', all_coins['BTC']['h'], all_coins['BTC']['l'],
                    all_coins['BTC']['c'], all_coins['BTC']['v'], all_coins['BTC']['t'])
    out = {}

    schemes = [
        ('基准-Dynamic', None),
        ('C-half(不一致降50%)', 0.5),
        ('C-70(不一致降30%)', 0.7),
        ('C-30(不一致降70%)', 0.3),
    ]

    # ===== 全期对比 =====
    print('========== 全期对比 (2023-2026) ==========', flush=True)
    results = {}
    for name, reduce in schemes:
        f = CAdjustFilter(btc_coin, reduce) if reduce is not None else None
        m = run_version(all_coins, START, END, f)
        results[name] = m
        print(f'  {name}: {fmt(m)}', flush=True)
    out['full'] = results

    # ===== 分年份 =====
    print('\n========== 分年份 ==========', flush=True)
    yearly = {}
    for pname, ps, pe in [('2023', START, MID), ('2024', MID, MID2), ('2025', MID2, END)]:
        yearly[pname] = {}
        for name, reduce in schemes:
            f = CAdjustFilter(btc_coin, reduce) if reduce is not None else None
            m = run_version(all_coins, ps, pe, f)
            yearly[pname][name] = m
        print(f'  [{pname}]', flush=True)
        for name in [s[0] for s in schemes]:
            m = yearly[pname][name]
            print(f'    {name}: 收益{m["total_ret"]:+.1f}% PF{m["pf"]:.2f} 回撤{m["max_dd"]:.1f}%', flush=True)
    out['yearly'] = yearly

    # ===== 震荡阶段专项 =====
    print('\n========== 震荡阶段 (24Q2-Q4) ==========', flush=True)
    seg_s = int(datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    seg_e = int(datetime.datetime(2024, 11, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    seg = {}
    for name, reduce in schemes:
        f = CAdjustFilter(btc_coin, reduce) if reduce is not None else None
        m = run_version(all_coins, seg_s, seg_e, f)
        seg[name] = m
        print(f'  {name}: 收益{m["total_ret"]:+.1f}% PF{m["pf"]:.2f} 回撤{m["max_dd"]:.1f}% 连亏{m["max_consec_loss"]}', flush=True)
    out['range'] = seg

    # ===== 下跌阶段 =====
    print('\n========== 下跌阶段 (23Q1-Q3) ==========', flush=True)
    dn_s = START
    dn_e = int(datetime.datetime(2023, 10, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    dn = {}
    for name, reduce in schemes:
        f = CAdjustFilter(btc_coin, reduce) if reduce is not None else None
        m = run_version(all_coins, dn_s, dn_e, f)
        dn[name] = m
        print(f'  {name}: 收益{m["total_ret"]:+.1f}% PF{m["pf"]:.2f} 回撤{m["max_dd"]:.1f}% 连亏{m["max_consec_loss"]}', flush=True)
    out['down'] = dn

    # ===== 升级判断 =====
    print('\n========== 升级判断 ==========', flush=True)
    base = results['基准-Dynamic']
    judge = {}
    for name in ['C-half(不一致降50%)', 'C-70(不一致降30%)', 'C-30(不一致降70%)']:
        m = results[name]
        ret_drop = (base['total_ret'] - m['total_ret']) / base['total_ret'] * 100 if base['total_ret'] > 0 else 0
        pf_diff = m['pf'] - base['pf']
        dd_diff = m['max_dd'] - base['max_dd']
        consec_diff = m['max_consec_loss'] - base['max_consec_loss']
        c1 = ret_drop < 20
        c2 = pf_diff > 0
        c3 = dd_diff < 0
        c4 = consec_diff <= 0
        judge[name] = {
            'ret_drop_pct': ret_drop, 'pf_diff': pf_diff, 'dd_diff': dd_diff,
            'consec_diff': consec_diff, 'checks': {'收益<20%': c1, 'PF升': c2, '回撤降': c3, '连亏不增': c4}
        }
        print(f'  {name}: 收益降{ret_drop:.1f}% PF{pf_diff:+.2f} 回撤{dd_diff:+.1f}% 连亏{consec_diff:+d}', flush=True)
        print(f'    收益<20%:{"✅" if c1 else "❌"} PF升:{"✅" if c2 else "❌"} 回撤降:{"✅" if c3 else "❌"} 连亏不增:{"✅" if c4 else "❌"}', flush=True)
    out['judge'] = judge

    with open(os.path.join(RESULTS, 'risk_adjust_results.json'), 'w') as f:
        json.dump(out, f, default=str, indent=2)
    print('\n完成, 结果: results/risk_adjust_results.json', flush=True)


if __name__ == '__main__':
    main()
