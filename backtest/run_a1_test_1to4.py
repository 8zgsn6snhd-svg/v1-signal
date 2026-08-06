# -*- coding: utf-8 -*-
"""A1上线前验证 测试1-4: 分年份/市场分段/趋势定义敏感性/反向强度"""
import os, sys, json, datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
import v1_engine
from pools import load_all_available, fixed_pool, dynamic_pool
from v1_engine import V1Backtest, Coin
from metrics import compute_metrics
from market_filter import (MarketState, BaseFilter, wrap_with_filter,
                           btc_atr_series, btc_ema120)

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


# ===== A1 过滤器 (ST3方向, 用户当前定义) =====
class A1Filter(BaseFilter):
    """BTC ST3方向过滤: 做多要求BTC趋势!=空头, 做空要求!=多头"""
    def __init__(self, btc_coin, trend_src='st3', ema_thresh=None):
        super().__init__(btc_coin)
        self.trend_src = trend_src  # 'st3'/'st2'/'st2st3'/'ema120'/'st3ema'
        self.ema_thresh = ema_thresh

    def _btc_dir(self, ts):
        idx = self.ms._idx(ts)
        if idx is None:
            return 0
        if self.trend_src == 'st3':
            return self.ms.btc.trends[2][idx] if idx >= 14 else 0
        elif self.trend_src == 'st2':
            return self.ms.btc.trends[1][idx] if idx >= 10 else 0
        elif self.trend_src == 'st2st3':
            d2 = self.ms.btc.trends[1][idx] if idx >= 10 else 0
            d3 = self.ms.btc.trends[2][idx] if idx >= 14 else 0
            if d2 == d3:
                return d2
            return 0  # 不一致视为无方向
        elif self.trend_src == 'ema120':
            if idx < 120:
                return 0
            return -1 if self.ms.btc.close[idx] > self.ms.ema120[idx] else 1
        elif self.trend_src == 'st3ema':
            d3 = self.ms.btc.trends[2][idx] if idx >= 14 else 0
            if idx < 120:
                return d3
            ema_dir = -1 if self.ms.btc.close[idx] > self.ms.ema120[idx] else 1
            if d3 == ema_dir:
                return d3
            return 0
        return 0

    def should_open(self, sig, ts):
        dirn = self._btc_dir(ts)
        if dirn == 0:
            return 1.0  # 无明确趋势, 不拦截
        # dirn: -1=多, 1=空
        conflict = (sig['dir'] == 1 and dirn == 1) or (sig['dir'] == -1 and dirn == -1)
        return 0.0 if conflict else 1.0


# ===== 反向强度过滤器 (测试4) =====
class ReverseStrengthFilter(BaseFilter):
    """不同反向强度: 'full'=BTC任何反向禁, 'st3'=ST3反向禁, 'two'=两线反向禁, 'three'=三线反向禁"""
    def __init__(self, btc_coin, level):
        super().__init__(btc_coin)
        self.level = level

    def _all_dirs(self, ts):
        idx = self.ms._idx(ts)
        if idx is None:
            return [0, 0, 0]
        return [self.ms.btc.trends[i][idx] if idx >= [6, 10, 14][i] else 0 for i in range(3)]

    def should_open(self, sig, ts):
        d1, d2, d3 = self._all_dirs(ts)
        # 定义BTC方向: -1多, 1空
        btc_bull = d3 == -1
        btc_bear = d3 == 1
        if self.level == 'full':
            # 用ST1方向 (最敏感)
            st1 = d1
            if st1 == 0:
                return 1.0
            conflict = (sig['dir'] == 1 and st1 == 1) or (sig['dir'] == -1 and st1 == -1)
            return 0.0 if conflict else 1.0
        elif self.level == 'st3':
            if d3 == 0:
                return 1.0
            conflict = (sig['dir'] == 1 and d3 == 1) or (sig['dir'] == -1 and d3 == -1)
            return 0.0 if conflict else 1.0
        elif self.level == 'two':
            # ST1/ST2/ST3中至少两个反方向
            cnt = 0
            for d in [d1, d2, d3]:
                if d == 0:
                    continue
                if sig['dir'] == 1 and d == 1:
                    cnt += 1
                if sig['dir'] == -1 and d == -1:
                    cnt += 1
            return 0.0 if cnt >= 2 else 1.0
        elif self.level == 'three':
            # 三线全部反向
            if d1 == 0 or d2 == 0 or d3 == 0:
                return 1.0
            cnt = 0
            for d in [d1, d2, d3]:
                if sig['dir'] == 1 and d == 1:
                    cnt += 1
                if sig['dir'] == -1 and d == -1:
                    cnt += 1
            return 0.0 if cnt == 3 else 1.0
        return 1.0


def fmt(m):
    return f"收益{m['total_ret']:>+8.1f}% PF{m['pf']:>6.2f} 回撤{m['max_dd']:>5.1f}% 交易{m['trades']:>5} 胜率{m['win_rate']:>5.1f}% 连亏{m['max_consec_loss']:>3}"


def main():
    all_coins = load_all_available()
    btc_coin = Coin('BTC', all_coins['BTC']['h'], all_coins['BTC']['l'],
                    all_coins['BTC']['c'], all_coins['BTC']['v'], all_coins['BTC']['t'])
    out = {}

    # ===== 测试1: 分年份 =====
    print('========== 测试1: 分年份验证 ==========', flush=True)
    periods = [('2023', START, MID), ('2024', MID, MID2), ('2025', MID2, END)]
    t1 = {}
    for pname, ps, pe in periods:
        m_base, _ = run_version(all_coins, ps, pe)
        a1 = A1Filter(btc_coin, 'st3')
        m_a1, _ = run_version(all_coins, ps, pe, a1)
        t1[pname] = {'base': m_base, 'a1': m_a1}
        print(f'\n[{pname}]', flush=True)
        print(f'  基准: {fmt(m_base)}', flush=True)
        print(f'  A1  : {fmt(m_a1)}', flush=True)
        print(f'  Δ   : 收益{m_a1["total_ret"]-m_base["total_ret"]:+.0f}% PF{m_a1["pf"]-m_base["pf"]:+.2f} '
              f'回撤{m_a1["max_dd"]-m_base["max_dd"]:+.1f}% 连亏{m_a1["max_consec_loss"]-m_base["max_consec_loss"]:+d}', flush=True)
    out['test1'] = t1

    # ===== 测试2: 市场分段 =====
    print('\n========== 测试2: 市场环境分段 ==========', flush=True)
    # 用BTC价格阶段定义: 上涨/下跌/震荡
    # 2023年初~2023-10 下跌; 2023-10~2024-03 上涨; 2024-03~2024-11 震荡; 2024-11~2026-01 上涨
    segs = [
        ('下跌期2023Q1-Q3', START, int(datetime.datetime(2023, 10, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)),
        ('上涨期2023Q4-2024Q1', int(datetime.datetime(2023, 10, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000),
         int(datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)),
        ('震荡期2024Q2-Q4', int(datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000),
         int(datetime.datetime(2024, 11, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)),
        ('上涨期2024Q4-2026', int(datetime.datetime(2024, 11, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000), END),
    ]
    t2 = {}
    for sname, ss, se in segs:
        m_base, _ = run_version(all_coins, ss, se)
        a1 = A1Filter(btc_coin, 'st3')
        m_a1, _ = run_version(all_coins, ss, se, a1)
        t2[sname] = {'base': m_base, 'a1': m_a1}
        print(f'\n[{sname}]', flush=True)
        print(f'  基准: 收益{m_base["total_ret"]:+.1f}% PF{m_base["pf"]:.2f} 回撤{m_base["max_dd"]:.1f}%', flush=True)
        print(f'  A1  : 收益{m_a1["total_ret"]:+.1f}% PF{m_a1["pf"]:.2f} 回撤{m_a1["max_dd"]:.1f}%', flush=True)
    out['test2'] = t2

    # ===== 测试3: BTC趋势定义敏感性 =====
    print('\n========== 测试3: BTC趋势定义敏感性 ==========', flush=True)
    trend_defs = [('A-ST3', 'st3'), ('B-ST2', 'st2'), ('C-ST2+ST3一致', 'st2st3'),
                  ('D-EMA120', 'ema120'), ('E-ST3+EMA120', 'st3ema')]
    m_base, _ = run_version(all_coins, START, END)
    t3 = {'base': m_base}
    for tname, tsrc in trend_defs:
        f = A1Filter(btc_coin, tsrc)
        m, _ = run_version(all_coins, START, END, f)
        t3[tname] = m
        print(f'  {tname}: 收益{m["total_ret"]:+.1f}% PF{m["pf"]:.2f} 回撤{m["max_dd"]:.1f}% 交易{m["trades"]}', flush=True)
    print(f'  基准   : 收益{m_base["total_ret"]:+.1f}% PF{m_base["pf"]:.2f} 回撤{m_base["max_dd"]:.1f}% 交易{m_base["trades"]}', flush=True)
    out['test3'] = t3

    # ===== 测试4: 反向强度 =====
    print('\n========== 测试4: 反向定义强度 ==========', flush=True)
    levels = [('v1-完全反向禁', 'full'), ('v2-ST3反向禁', 'st3'),
              ('v3-两线反向禁', 'two'), ('v4-三线反向禁', 'three')]
    t4 = {'base': m_base}
    for lname, lvl in levels:
        f = ReverseStrengthFilter(btc_coin, lvl)
        m, _ = run_version(all_coins, START, END, f)
        t4[lname] = m
        print(f'  {lname}: 收益{m["total_ret"]:+.1f}% PF{m["pf"]:.2f} 回撤{m["max_dd"]:.1f}% 交易{m["trades"]}', flush=True)
    out['test4'] = t4

    with open(os.path.join(RESULTS, 'a1_test_1to4.json'), 'w') as f:
        json.dump(out, f, default=str, indent=2)
    print('\n测试1-4完成, 结果: results/a1_test_1to4.json', flush=True)


if __name__ == '__main__':
    main()
