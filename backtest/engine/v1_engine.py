# -*- coding: utf-8 -*-
"""V1 回测引擎 — 忠实复现 V1.8 生产规格 (冻结)

策略规则 (来自 v1_final_spec.md + signal/index.js 生产代码, 禁止改动):
- 信号: C信号 (三线刚同向翻转) ST1(6,1) ST2(10,2.5) ST3(14,5)
- 过滤: 成交量 > 50% 90日均值
- 过滤: ST距离 <= 3% (核心质量过滤器)
- 入场: 时间优先 (最早C信号), 最多3仓, 满仓锁定不替换
- 仓位: 固定风险 每笔1%账户, 仓位 = 风险金额 / ST1距离, 上限50%
- 退出: 止损ST1线, 止盈5R, 超时240bars
- BTC: 反色只平仓 (不禁入), 监控BTC 4H ST1 绿->红 平全部

Supertrend 实现精确翻译自 signal/index.js st(), 方向语义一致:
dr=-1 = 多头(绿) ln=lower band; dr=1 = 空头(红) ln=upper band
"""
import math

# ============ 常量 (冻结, 不可改) ============
ST_PARAMS = [(6, 1.0), (10, 2.5), (14, 5.0)]
VOL_FILTER = 0.5
ST_DIST_MAX = 3.0   # %
TP_R = 5.0
TIMEOUT_BARS = 240
MAX_POS = 3
RISK_PER_TRADE = 0.01
MAX_POS_PCT = 0.50
FEES = 0.0005      # 单边 0.05% 手续费
SLIPPAGE = 0.0003  # 单边 0.03% 滑点

def supertrend(high, low, close, period, mult):
    """精确翻译 signal/index.js st(). 返回 (dr数组, ln数组)"""
    n = len(close)
    if n < period:
        return None, None
    hl = [(h + l) / 2 for h, l in zip(high, low)]
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]))
    atr = [0.0] * n
    s = 0.0
    for i in range(0, period):
        s += tr[i]
    atr[period - 1] = s / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    up = [0.0] * n
    lo = [0.0] * n
    ln = [0.0] * n
    dr = [0] * n
    up[period - 1] = hl[period - 1] + mult * atr[period - 1]
    lo[period - 1] = hl[period - 1] - mult * atr[period - 1]
    dr[period - 1] = 1
    ln[period - 1] = up[period - 1]
    for i in range(period, n):
        u = hl[i] + mult * atr[i]
        lw = hl[i] - mult * atr[i]
        up[i] = u if (u < up[i - 1] or close[i - 1] > up[i - 1]) else up[i - 1]
        lo[i] = lw if (lw > lo[i - 1] or close[i - 1] < lo[i - 1]) else lo[i - 1]
        x = abs(ln[i - 1] - up[i - 1]) < abs(ln[i - 1] - lo[i - 1])
        dr[i] = -1 if (x and close[i] > up[i]) else (1 if (x and close[i] <= up[i]) else (1 if (not x and close[i] < lo[i]) else -1))
        ln[i] = lo[i] if dr[i] == -1 else up[i]
    return dr, ln

class Coin:
    """单币数据 + ST指标"""
    def __init__(self, symbol, high, low, close, vol, ts):
        self.symbol = symbol
        self.high, self.low, self.close, self.vol, self.ts = high, low, close, vol, ts
        self.n = len(close)
        self.trends = []   # list of dr数组
        self.lines = []    # list of ln数组
        for p, m in ST_PARAMS:
            t, l = supertrend(high, low, close, p, m)
            self.trends.append(t)
            self.lines.append(l)

    def c_signal(self, idx):
        """C信号: 当前三线同向(dr相等) 且 上一根非三线同向.
        精确翻译 an() 的 cT 判定."""
        if idx < 1 or idx >= self.n - 1:
            return False
        d1, d2, d3 = self.trends[0][idx], self.trends[1][idx], self.trends[2][idx]
        if not (d1 == d2 == d3):
            return False
        pd1, pd2, pd3 = self.trends[0][idx - 1], self.trends[1][idx - 1], self.trends[2][idx - 1]
        return not (pd1 == pd2 == pd3)

    def vol_ok(self, idx):
        """成交量过滤: 翻译 an() 的 cv<av*VOL_FILTER 过滤.
        生产: ix=c.length-2, cv=vl[ix], lb=min(90,ix-1), av=mean(vl[ix-lb..ix-1])"""
        if idx < 1:
            return True  # 无足够历史, 不过滤
        cv = self.vol[idx]
        lb = min(90, idx - 1)
        if lb <= 0:
            return True
        av = 0.0
        for j in range(idx - lb, idx):
            av += self.vol[j]
        av /= lb
        if av <= 0:
            return True
        return not (cv < av * VOL_FILTER)

    def st_dist(self, idx):
        """ST距离 % = |close - ST1线| / close * 100"""
        close = self.close[idx]
        l1 = self.lines[0][idx]
        if close <= 0:
            return 99.0
        return abs(close - l1) / close * 100.0

class V1Backtest:
    def __init__(self, coins_data, start_ts, end_ts, initial=10000,
                 pool_provider=None, pool_update_bars=1):
        """coins_data: dict {symbol: {h,l,c,v,t}} 已按ts升序
        pool_provider: callable(bar_index, ts, current_pool) -> list[str], 可选
        pool_update_bars: 每N根bar重新评估池子"""
        self.coins = {}
        for sym, d in coins_data.items():
            self.coins[sym] = Coin(sym, d['h'], d['l'], d['c'], d['v'], d['t'])
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.initial = initial
        self.pool_provider = pool_provider
        self.pool_update_bars = pool_update_bars
        all_ts = set()
        for c in self.coins.values():
            all_ts.update(c.ts)
        self.timeline = sorted(t for t in all_ts if start_ts <= t < end_ts)
        self.equity = []
        self.trades = []
        self.balance = initial
        self.positions = {}
        self.current_pool = None

    def _c_idx(self, sym, ts):
        """返回该币时间轴中 <=ts 的最近 index"""
        c = self.coins[sym]
        lo, hi = 0, len(c.ts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if c.ts[mid] == ts:
                return mid
            elif c.ts[mid] < ts:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi

    def _find_signal(self, sym, ts):
        """ts处该币是否C信号+过滤, 返回详情或None"""
        c = self.coins[sym]
        idx = self._c_idx(sym, ts)
        if idx is None or idx < 1 or idx >= c.n - 1:
            return None
        # 必须是 ts 恰好对应这根bar的收盘确认 (用同bar判定)
        # 生产: 用 ix=c.length-2 (倒数第二根) 即"已收盘bar"
        # 这里 idx 是最接近ts的bar, 若ts正好是该bar开盘则信号未确认, 跳过
        if c.ts[idx] != ts:
            return None
        if not c.c_signal(idx):
            return None
        if not c.vol_ok(idx):
            return None
        dist = c.st_dist(idx)
        if dist > ST_DIST_MAX:
            return None
        direction = -1 if c.trends[0][idx] == -1 else 1  # dr=-1=多, dr=1=空
        entry_price = c.close[idx]
        stop = c.lines[0][idx]
        return {'sym': sym, 'dir': direction, 'entry': entry_price,
                'stop': stop, 'dist': dist, 'idx': idx}

    def run(self):
        """主循环: 逐bar扫描当前池币, 找C信号; 管理持仓退出"""
        self.current_pool = list(self.coins.keys())
        for bi, ts in enumerate(self.timeline):
            if self.pool_provider is not None and bi % self.pool_update_bars == 0:
                new_pool = self.pool_provider(bi, ts, self.current_pool)
                if new_pool is not None and len(new_pool) > 0:
                    self.current_pool = new_pool

            # 1. 持仓退出检查
            for sym in list(self.positions.keys()):
                pos = self.positions[sym]
                c = self.coins[sym]
                idx = self._c_idx(sym, ts)
                if idx is None or c.ts[idx] != ts:
                    continue  # 该币此bar无数据, 跳过
                pos['bars_held'] += 1
                if pos['bars_held'] >= TIMEOUT_BARS:
                    self._close(sym, c.close[idx], 'TIMEOUT', ts, idx)
                    continue
                cur_close = c.close[idx]
                if pos['dir'] == 1 and cur_close < pos['stop']:
                    self._close(sym, pos['stop'], 'STOP', ts, idx)
                    continue
                if pos['dir'] == -1 and cur_close > pos['stop']:
                    self._close(sym, pos['stop'], 'STOP', ts, idx)
                    continue
                R = abs(pos['entry'] - pos['stop'])
                if pos['dir'] == 1 and cur_close >= pos['entry'] + TP_R * R:
                    self._close(sym, pos['entry'] + TP_R * R, 'TP', ts, idx)
                    continue
                if pos['dir'] == -1 and cur_close <= pos['entry'] - TP_R * R:
                    self._close(sym, pos['entry'] - TP_R * R, 'TP', ts, idx)
                    continue

            # 2. BTC反色平仓: ST1 绿->红 (dr -1 -> 1)
            if 'BTC' in self.coins and self.positions:
                btc = self.coins['BTC']
                idx = self._c_idx('BTC', ts)
                if idx is not None and idx >= 1 and btc.ts[idx] == ts:
                    if btc.trends[0][idx - 1] == -1 and btc.trends[0][idx] == 1:
                        for sym in list(self.positions.keys()):
                            ci = self._c_idx(sym, ts)
                            if ci is not None and self.coins[sym].ts[ci] == ts:
                                self._close(sym, self.coins[sym].close[ci], 'BTC_REV', ts, ci)

            # 3. 新开仓 (时间优先, 满仓锁定, 只扫当前池)
            if len(self.positions) < MAX_POS:
                signals = []
                for sym in self.current_pool:
                    if sym not in self.coins:
                        continue
                    sig = self._find_signal(sym, ts)
                    if sig:
                        signals.append(sig)
                signals.sort(key=lambda s: s['sym'])
                for sig in signals:
                    if len(self.positions) >= MAX_POS:
                        break
                    if sig['sym'] in self.positions:
                        continue
                    self._open(sig, ts)

            # 4. 更新权益
            eq = self.balance
            for sym, pos in self.positions.items():
                c = self.coins[sym]
                idx = self._c_idx(sym, ts)
                if idx is not None:
                    pnl = pos['dir'] * (c.close[idx] - pos['entry']) / pos['entry'] * pos['qty']
                    eq += pnl
            self.equity.append((ts, eq))

        return {'equity': self.equity, 'trades': self.trades}

    def _open(self, sig, ts):
        """固定风险开仓: 仓位 = 风险金额 / ST1距离%"""
        entry = sig['entry']
        R = abs(entry - sig['stop'])
        if R <= 0:
            return
        risk_amount = self.balance * RISK_PER_TRADE
        pos_value = risk_amount / (R / entry)
        max_val = self.balance * MAX_POS_PCT
        pos_value = min(pos_value, max_val)
        if pos_value <= 0:
            return
        self.positions[sig['sym']] = {
            'entry_ts': ts, 'entry': entry, 'stop': sig['stop'],
            'qty': pos_value, 'dir': sig['dir'], 'entry_idx': sig['idx'],
            'bars_held': 0, 'risk_amount': risk_amount
        }

    def _close(self, sym, exit_price, reason, ts, idx):
        pos = self.positions.pop(sym)
        if exit_price is None:
            exit_price = self.coins[sym].close[idx]
        ret = pos['dir'] * (exit_price - pos['entry']) / pos['entry'] - FEES * 2 - SLIPPAGE * 2
        pnl = ret * pos['qty']
        self.balance += pnl
        self.trades.append({
            'symbol': sym, 'dir': pos['dir'], 'entry_ts': pos['entry_ts'],
            'exit_ts': ts, 'entry': pos['entry'], 'exit': exit_price,
            'reason': reason, 'pnl': pnl, 'ret': ret, 'bars': pos['bars_held'],
            'qty': pos['qty'], 'risk_amount': pos['risk_amount'],
            'R_multiple': pnl / pos['risk_amount'] if pos['risk_amount'] else 0
        })

    def close_all(self):
        """结束时平所有仓"""
        for sym in list(self.positions.keys()):
            c = self.coins[sym]
            idx = len(c.ts) - 1
            self._close(sym, c.close[idx], 'END', self.timeline[-1], idx)
