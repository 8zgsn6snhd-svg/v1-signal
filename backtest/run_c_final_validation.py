# -*- coding: utf-8 -*-
"""C方案 (BTC ST2+ST3一致过滤) 上线前最终验证

C方案规则:
- 做多允许: BTC ST2=多 且 ST3=多
- 做空允许: BTC ST2=空 且 ST3=空
- ST2与ST3不一致: 禁止新开仓

验证: 分年份/市场分段/手续费/延迟/三版本对比
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


def run_version(all_coins, s, e, filter_obj=None, delay=0, fees=0.0005, slippage=0.0003):
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


# ===== C方案过滤器: ST2+ST3一致, 不一致禁止 =====
class CFilter(BaseFilter):
    def __init__(self, btc_coin):
        super().__init__(btc_coin)

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
            return 0.0  # 数据不足, 禁止(保守)
        if d2 != d3:
            return 0.0  # 方向不一致, 禁止开仓 (C方案核心)
        btc_dir = d2  # -1=多, 1=空
        # 只允许顺势
        if sig['dir'] == 1 and btc_dir == -1:   # 做多 & BTC多
            return 1.0
        if sig['dir'] == -1 and btc_dir == 1:   # 做空 & BTC空
            return 1.0
        return 0.0  # 逆势禁止


# ===== A1-ST3过滤器 (对比用, 同之前) =====
class A1ST3Filter(BaseFilter):
    def should_open(self, sig, ts):
        idx = self.ms._idx(ts)
        if idx is None or idx < 14:
            return 0.0
        d3 = self.ms.btc.trends[2][idx]
        if d3 == 0:
            return 0.0
        conflict = (sig['dir'] == 1 and d3 == 1) or (sig['dir'] == -1 and d3 == -1)
        return 0.0 if conflict else 1.0


def fmt(m):
    return (f"收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% "
            f"交易{m['trades']:>5} 胜率{m['win_rate']:>5.1f}% 连亏{m['max_consec_loss']:>3}")


def main():
    all_coins = load_all_available()
    btc_coin = Coin('BTC', all_coins['BTC']['h'], all_coins['BTC']['l'],
                    all_coins['BTC']['c'], all_coins['BTC']['v'], all_coins['BTC']['t'])
    out = {}

    # ===== 1. 分年份 =====
    print('========== 1. 分年份验证 ==========', flush=True)
    periods = [('2023', START, MID), ('2024', MID, MID2), ('2025', MID2, END)]
    t1 = {}
    for pname, ps, pe in periods:
        m_base, _ = run_version(all_coins, ps, pe)
        c_f = CFilter(btc_coin)
        m_c, skipped = run_version(all_coins, ps, pe, c_f)
        t1[pname] = {'base': m_base, 'c': m_c}
        print(f'\n[{pname}]', flush=True)
        print(f'  基准: {fmt(m_base)}', flush=True)
        print(f'  C   : {fmt(m_c)} 跳过{skipped}', flush=True)
        print(f'  Δ   : 收益{m_c["total_ret"]-m_base["total_ret"]:+.0f}% PF{m_c["pf"]-m_base["pf"]:+.2f} '
              f'回撤{m_c["max_dd"]-m_base["max_dd"]:+.1f}% 连亏{m_c["max_consec_loss"]-m_base["max_consec_loss"]:+d}', flush=True)
    out['test1'] = t1

    # ===== 2. 市场分段 =====
    print('\n========== 2. 市场环境分段 ==========', flush=True)
    segs = [
        ('下跌期23Q1-Q3', START, int(datetime.datetime(2023, 10, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)),
        ('上涨期23Q4-24Q1', int(datetime.datetime(2023, 10, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000),
         int(datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)),
        ('震荡期24Q2-Q4', int(datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000),
         int(datetime.datetime(2024, 11, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)),
        ('上涨期24Q4-26', int(datetime.datetime(2024, 11, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000), END),
    ]
    t2 = {}
    for sname, ss, se in segs:
        m_base, _ = run_version(all_coins, ss, se)
        c_f = CFilter(btc_coin)
        m_c, _ = run_version(all_coins, ss, se, c_f)
        t2[sname] = {'base': m_base, 'c': m_c}
        print(f'  [{sname}] 基准: 收益{m_base["total_ret"]:+.1f}% PF{m_base["pf"]:.2f} 回撤{m_base["max_dd"]:.1f}% | '
              f'C: 收益{m_c["total_ret"]:+.1f}% PF{m_c["pf"]:.2f} 回撤{m_c["max_dd"]:.1f}%', flush=True)
    out['test2'] = t2

    # ===== 3. 手续费压力 =====
    print('\n========== 3. 手续费压力 ==========', flush=True)
    fee_levels = [('0.08%', 0.0004, 0.0004), ('0.15%', 0.00075, 0.00075), ('0.25%', 0.00125, 0.00125)]
    t3 = {}
    for fname, fee, slip in fee_levels:
        m_base, _ = run_version(all_coins, START, END, None, fees=fee, slippage=slip)
        c_f = CFilter(btc_coin)
        m_c, _ = run_version(all_coins, START, END, c_f, fees=fee, slippage=slip)
        t3[fname] = {'base': m_base, 'c': m_c}
        print(f'  [{fname}] 基准: {fmt(m_base)} | C: {fmt(m_c)}', flush=True)
    out['test3'] = t3

    # ===== 4. 延迟成交 =====
    print('\n========== 4. 延迟成交 ==========', flush=True)
    t4 = {}
    for dname, delay in [('立即成交', 0), ('延迟1根', 1)]:
        m_base, _ = run_version(all_coins, START, END, None, delay=delay)
        c_f = CFilter(btc_coin)
        m_c, _ = run_version(all_coins, START, END, c_f, delay=delay)
        t4[dname] = {'base': m_base, 'c': m_c}
        print(f'  [{dname}] 基准: {fmt(m_base)} | C: {fmt(m_c)}', flush=True)
    out['test4'] = t4

    # ===== 5. 三版本对比 =====
    print('\n========== 5. 三版本对比 ==========', flush=True)
    m_base, _ = run_version(all_coins, START, END)
    a1_f = A1ST3Filter(btc_coin)
    m_a1, sk_a1 = run_version(all_coins, START, END, a1_f)
    c_f = CFilter(btc_coin)
    m_c, sk_c = run_version(all_coins, START, END, c_f)
    t5 = {'base': m_base, 'a1': m_a1, 'c': m_c}
    print(f'  原Dynamic: {fmt(m_base)}', flush=True)
    print(f'  A1-ST3   : {fmt(m_a1)} 跳过{sk_a1}', flush=True)
    print(f'  C方案    : {fmt(m_c)} 跳过{sk_c}', flush=True)

    # 升级判断
    print('\n========== 升级判断 ==========', flush=True)
    ret_drop = (m_base['total_ret'] - m_c['total_ret']) / m_base['total_ret'] * 100 if m_base['total_ret'] > 0 else 0
    pf_up = m_c['pf'] - m_base['pf']
    dd_down = m_c['max_dd'] - m_base['max_dd']
    print(f'  收益变化: {m_c["total_ret"]:+.1f}% vs 基准 {m_base["total_ret"]:+.1f}% (下降{ret_drop:.1f}%)', flush=True)
    print(f'  PF变化: {m_c["pf"]:.2f} vs {m_base["pf"]:.2f} ({pf_up:+.2f})', flush=True)
    print(f'  回撤变化: {m_c["max_dd"]:.1f}% vs {m_base["max_dd"]:.1f}% ({dd_down:+.1f}%)', flush=True)
    print(f'  震荡期: 待查test2', flush=True)
    checks = {
        '收益下降<20%': ret_drop < 20,
        'PF提升': pf_up > 0,
        '回撤下降': dd_down < 0,
    }
    for k, v in checks.items():
        print(f'  {k}: {"✅" if v else "❌"}', flush=True)
    out['judge'] = {'ret_drop_pct': ret_drop, 'pf_diff': pf_up, 'dd_diff': dd_down, 'checks': checks}

    with open(os.path.join(RESULTS, 'c_final_validation.json'), 'w') as f:
        json.dump(out, f, default=str, indent=2)
    print('\n完成, 结果: results/c_final_validation.json', flush=True)


if __name__ == '__main__':
    main()
