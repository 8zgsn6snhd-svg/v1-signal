# -*- coding: utf-8 -*-
"""市场状态过滤模块 v2 — 独立测试, 不改引擎核心

方案A: BTC趋势一致过滤 (反向禁开/降仓50%)
方案B: BTC ST状态过滤 (ST3冲突禁开/降仓)
方案C: ATR震荡过滤 (ATR<均值×0.8 禁开/降仓)
方案D: ADX趋势强度过滤 (ADX<20 禁开/降仓)
方案E: 综合市场状态评分
方案F: 山寨自身趋势确认 (ST1方向持续≥2根)
方案G: 同币止损冷却 (止损后24根不再开)
方案H: BTC趋势持续确认 (反向方向持续≥6根才认定)
方案I: 山寨自身ATR波动过滤 (自身ATR<90日均值×0.8禁开)
方案J: BTC趋势+ADX分级 (同向ADX>25满仓/同向正常/反向禁)
方案K: 每日新仓上限 (同一天最多N个新仓)

过滤器对象: should_open(sig, ts)->mult, on_open(sym,ts), on_close(sym,ts,reason)
"""
import math
from collections import defaultdict


# ===== BTC 指标计算 =====
def btc_atr_series(coin, period=14):
    n = coin.n
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(coin.high[i] - coin.low[i],
                    abs(coin.high[i] - coin.close[i - 1]),
                    abs(coin.low[i] - coin.close[i - 1]))
    atr = [0.0] * n
    s = sum(tr[:period])
    atr[period - 1] = s / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def btc_atr_avg90(atr_series, idx):
    lo = max(0, idx - 89)
    if idx - lo + 1 < 20:
        return None
    return sum(atr_series[lo:idx + 1]) / (idx - lo + 1)


def btc_ema120(coin):
    n = coin.n
    period = 120
    ema = [0.0] * n
    k = 2.0 / (period + 1)
    s = sum(coin.close[:period])
    ema[period - 1] = s / period
    for i in range(period, n):
        ema[i] = coin.close[i] * k + ema[i - 1] * (1 - k)
    return ema


def btc_adx_series(coin, period=14):
    n = coin.n
    if n < period + 1:
        return [0.0] * n
    tr = [0.0] * n
    pdm = [0.0] * n
    mdm = [0.0] * n
    for i in range(1, n):
        up = coin.high[i] - coin.high[i - 1]
        dn = coin.low[i - 1] - coin.low[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(coin.high[i] - coin.low[i],
                    abs(coin.high[i] - coin.close[i - 1]),
                    abs(coin.low[i] - coin.close[i - 1]))
    atr = [0.0] * n
    pdi = [0.0] * n
    mdi = [0.0] * n
    atr[period] = sum(tr[1:period + 1]) / period
    pdi[period] = sum(pdm[1:period + 1]) / period
    mdi[period] = sum(mdm[1:period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        pdi[i] = (pdi[i - 1] * (period - 1) + pdm[i]) / period
        mdi[i] = (mdi[i - 1] * (period - 1) + mdm[i]) / period
    dx = [0.0] * n
    for i in range(period + 1, n):
        denom = pdi[i] + mdi[i]
        if denom > 0:
            dx[i] = abs(pdi[i] - mdi[i]) / denom * 100.0
    adx = [0.0] * n
    if n > period * 2:
        s = sum(dx[period + 1:period * 2])
        adx[period * 2] = s / period
        for i in range(period * 2 + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


class MarketState:
    """预计算BTC市场状态, 供过滤器查询"""
    def __init__(self, btc_coin):
        self.btc = btc_coin
        self.atr14 = btc_atr_series(btc_coin, 14)
        self.ema120 = btc_ema120(btc_coin)
        self.adx14 = btc_adx_series(btc_coin, 14)

    def _idx(self, ts):
        c = self.btc
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

    def price_vs_ema120(self, ts):
        idx = self._idx(ts)
        if idx is None or idx < 120:
            return 0
        return 1 if self.btc.close[idx] > self.ema120[idx] else -1

    def st3_dir(self, ts):
        idx = self._idx(ts)
        if idx is None or idx < 14:
            return 0
        return self.btc.trends[2][idx]

    def st1_dir(self, ts):
        idx = self._idx(ts)
        if idx is None or idx < 6:
            return 0
        return self.btc.trends[0][idx]

    def st1_dir_persist(self, ts, n_bars=6):
        """BTC ST1在ts往前n_bars是否持续同方向. 返回方向(-1多/1空)或0"""
        idx = self._idx(ts)
        if idx is None or idx < 6 + n_bars:
            return 0
        d = self.btc.trends[0][idx]
        for i in range(idx - n_bars + 1, idx + 1):
            if self.btc.trends[0][i] != d:
                return 0
        return d

    def st_dirs(self, ts):
        idx = self._idx(ts)
        if idx is None:
            return [0, 0, 0]
        return [self.btc.trends[i][idx] if idx < len(self.btc.trends[i]) else 0 for i in range(3)]

    def adx(self, ts):
        idx = self._idx(ts)
        if idx is None or idx >= len(self.adx14):
            return 0
        return self.adx14[idx]

    def atr_now(self, ts):
        idx = self._idx(ts)
        if idx is None or idx >= len(self.atr14):
            return None
        return self.atr14[idx]

    def atr_avg(self, ts):
        idx = self._idx(ts)
        if idx is None:
            return None
        return btc_atr_avg90(self.atr14, idx)


# ===== 过滤器对象 =====
class Filter:
    def should_open(self, sig, ts):
        return 1.0

    def on_open(self, sym, ts):
        pass

    def on_close(self, sym, ts, reason):
        pass


class BaseFilter(Filter):
    """通用过滤器基类"""
    def __init__(self, btc_coin):
        self.ms = MarketState(btc_coin)


# ===== 各方案 =====
class SchemeA(BaseFilter):
    """BTC趋势一致过滤"""
    def __init__(self, btc_coin, variant):
        super().__init__(btc_coin)
        self.variant = variant

    def should_open(self, sig, ts):
        st1 = self.ms.st1_dir(ts)
        if st1 == 0:
            return 1.0
        conflict = (sig['dir'] == 1 and st1 == 1) or (sig['dir'] == -1 and st1 == -1)
        if not conflict:
            return 1.0
        if self.variant == 'ban':
            return 0.0
        return 0.5


class SchemeB(BaseFilter):
    """BTC ST状态过滤"""
    def __init__(self, btc_coin, variant):
        super().__init__(btc_coin)
        self.variant = variant

    def should_open(self, sig, ts):
        d1, d2, d3 = self.ms.st_dirs(ts)
        if d1 == 0 or d2 == 0 or d3 == 0:
            return 1.0
        conflict = (d1 == d2 and d3 != d1)
        if not conflict:
            return 1.0
        if self.variant == 'ban':
            return 0.0
        return 0.5


class SchemeC(BaseFilter):
    """ATR震荡过滤 (BTC ATR)"""
    def __init__(self, btc_coin, variant):
        super().__init__(btc_coin)
        self.variant = variant

    def should_open(self, sig, ts):
        atr = self.ms.atr_now(ts)
        avg = self.ms.atr_avg(ts)
        if atr is None or avg is None or avg <= 0:
            return 1.0
        if atr < avg * 0.8:
            if self.variant == 'ban':
                return 0.0
            return 0.5
        return 1.0


class SchemeD(BaseFilter):
    """ADX趋势强度过滤"""
    def __init__(self, btc_coin, variant):
        super().__init__(btc_coin)
        self.variant = variant

    def should_open(self, sig, ts):
        adx = self.ms.adx(ts)
        if adx <= 0:
            return 1.0
        if adx < 20:
            if self.variant == 'ban':
                return 0.0
            return 0.5
        return 1.0


class SchemeE(BaseFilter):
    """综合市场状态评分"""
    def should_open(self, sig, ts):
        score = 0
        if self.ms.price_vs_ema120(ts) == 1:
            score += 1
        st3 = self.ms.st3_dir(ts)
        if st3 == -1 and sig['dir'] == 1:
            score += 1
        elif st3 == 1 and sig['dir'] == -1:
            score += 1
        if self.ms.adx(ts) > 25:
            score += 1
        atr = self.ms.atr_now(ts)
        avg = self.ms.atr_avg(ts)
        if atr is not None and avg is not None and avg > 0 and atr > avg:
            score += 1
        if score >= 4:
            return 1.0
        elif score >= 2:
            return 0.5
        return 0.0


class SchemeF(BaseFilter):
    """山寨自身趋势确认: 信号币ST1方向已持续≥2根"""
    def __init__(self, btc_coin, coins_data):
        super().__init__(btc_coin)
        self.coins_data = coins_data

    def should_open(self, sig, ts):
        sym = sig['sym']
        d = self.coins_data.get(sym)
        if not d:
            return 1.0
        # sig['idx'] 是信号bar index
        idx = sig.get('idx')
        if idx is None or idx < 2:
            return 1.0
        # 检查该币ST1方向在idx和idx-1是否同向
        # 需要Coin的trends, 这里简化: 用价格连续2根同向
        c = d['c']
        if idx < 1:
            return 1.0
        up1 = c[idx] > c[idx - 1]
        up0 = c[idx - 1] > c[idx - 2] if idx >= 2 else up1
        trend_up = up0 and up1
        trend_dn = (not up0) and (not up1)
        # 做多需连续2根涨, 做空需连续2根跌
        if sig['dir'] == 1:
            return 1.0 if trend_up else 0.0
        else:
            return 1.0 if trend_dn else 0.0


class SchemeG(BaseFilter):
    """同币止损冷却: 止损后cooldown_bars根不再开"""
    def __init__(self, btc_coin, cooldown_bars=24):
        super().__init__(btc_coin)
        self.cooldown = cooldown_bars
        self.last_stop = {}   # sym -> ts

    def should_open(self, sig, ts):
        sym = sig['sym']
        last = self.last_stop.get(sym)
        if last is not None:
            if ts - last < self.cooldown * 4 * 3600 * 1000:
                return 0.0
        return 1.0

    def on_close(self, sym, ts, reason):
        if reason == 'STOP':
            self.last_stop[sym] = ts


class SchemeH(BaseFilter):
    """BTC趋势持续确认: 反向方向需持续≥n_bars才禁"""
    def __init__(self, btc_coin, n_bars=6):
        super().__init__(btc_coin)
        self.n_bars = n_bars

    def should_open(self, sig, ts):
        persist_dir = self.ms.st1_dir_persist(ts, self.n_bars)
        if persist_dir == 0:
            return 1.0  # 未确认趋势, 正常(可能刚翻转)
        conflict = (sig['dir'] == 1 and persist_dir == 1) or (sig['dir'] == -1 and persist_dir == -1)
        return 0.0 if conflict else 1.0


class SchemeI(BaseFilter):
    """山寨自身ATR波动过滤: 该币ATR<自身90日均值×0.8禁开"""
    def __init__(self, btc_coin, coins_data):
        super().__init__(btc_coin)
        self.coins_data = coins_data

    def should_open(self, sig, ts):
        sym = sig['sym']
        d = self.coins_data.get(sym)
        if not d:
            return 1.0
        h, l, c = d['h'], d['l'], d['c']
        idx = sig.get('idx')
        if idx is None or idx < 100:
            return 1.0
        # 计算该币ATR14
        atr = [0.0] * (idx + 1)
        tr = [0.0] * (idx + 1)
        for i in range(1, idx + 1):
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        s = sum(tr[1:15])
        atr[14] = s / 14
        for i in range(15, idx + 1):
            atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
        cur_atr = atr[idx]
        avg_lo = max(0, idx - 89)
        avg = sum(atr[avg_lo:idx + 1]) / (idx - avg_lo + 1) if idx - avg_lo + 1 >= 20 else None
        if avg is None or avg <= 0:
            return 1.0
        if cur_atr < avg * 0.8:
            return 0.0
        return 1.0


class SchemeJ(BaseFilter):
    """BTC趋势+ADX分级: 同向ADX>25满仓/同向正常/反向禁"""
    def should_open(self, sig, ts):
        st1 = self.ms.st1_dir(ts)
        adx = self.ms.adx(ts)
        if st1 == 0:
            return 1.0
        conflict = (sig['dir'] == 1 and st1 == 1) or (sig['dir'] == -1 and st1 == -1)
        if conflict:
            return 0.0
        # 同向: ADX>25满仓, 否则正常
        if adx > 25:
            return 1.0
        return 1.0


class SchemeK(BaseFilter):
    """每日新仓上限: 同一天最多N个新仓"""
    def __init__(self, btc_coin, max_daily=2):
        super().__init__(btc_coin)
        self.max_daily = max_daily
        self.day_count = defaultdict(int)
        self.cur_day = None

    def should_open(self, sig, ts):
        day = ts // (24 * 3600 * 1000)
        if day != self.cur_day:
            self.cur_day = day
            self.day_count.clear()
        if self.day_count[sig['sym']] >= 1:
            return 0.0  # 同币每天最多1次
        total = sum(self.day_count.values())
        if total >= self.max_daily:
            return 0.0
        return 1.0

    def on_open(self, sym, ts):
        day = ts // (24 * 3600 * 1000)
        if day != self.cur_day:
            self.cur_day = day
            self.day_count.clear()
        self.day_count[sym] += 1


# ===== 工厂 =====
def make_filter(scheme, variant, btc_coin, coins_data=None, params=None):
    """创建过滤器对象"""
    params = params or {}
    scheme = scheme.lower()
    variant = (variant or '').lower()
    if scheme == 'a':
        return SchemeA(btc_coin, variant)
    if scheme == 'b':
        return SchemeB(btc_coin, variant)
    if scheme == 'c':
        return SchemeC(btc_coin, variant)
    if scheme == 'd':
        return SchemeD(btc_coin, variant)
    if scheme == 'e':
        return SchemeE(btc_coin)
    if scheme == 'f':
        return SchemeF(btc_coin, coins_data)
    if scheme == 'g':
        return SchemeG(btc_coin, params.get('cooldown_bars', 24))
    if scheme == 'h':
        return SchemeH(btc_coin, params.get('n_bars', 6))
    if scheme == 'i':
        return SchemeI(btc_coin, coins_data)
    if scheme == 'j':
        return SchemeJ(btc_coin)
    if scheme == 'k':
        return SchemeK(btc_coin, params.get('max_daily', 2))
    raise ValueError(f'Unknown scheme {scheme}')


# ===== 引擎包装 =====
def wrap_with_filter(engine_cls, filter_obj):
    """创建子类, 覆盖_open/_close应用市场过滤"""
    class FilteredEngine(engine_cls):
        def __init__(self, *args, **kwargs):
            self._filter = filter_obj
            super().__init__(*args, **kwargs)

        def _open(self, sig, ts):
            mult = self._filter.should_open(sig, ts) if self._filter else 1.0
            if mult <= 0:
                self._filter_skipped = getattr(self, '_filter_skipped', 0) + 1
                return
            super()._open(sig, ts)
            if sig['sym'] in self.positions:
                pos = self.positions[sig['sym']]
                pos['qty'] *= mult
                pos['risk_amount'] *= mult
                if self._filter:
                    self._filter.on_open(sig['sym'], ts)

        def _close(self, sym, exit_price, reason, ts, idx):
            if self._filter:
                self._filter.on_close(sym, ts, reason)
            super()._close(sym, exit_price, reason, ts, idx)

        @property
        def skipped_count(self):
            return getattr(self, '_filter_skipped', 0)

    return FilteredEngine
