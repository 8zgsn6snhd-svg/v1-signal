# -*- coding: utf-8 -*-
"""三版本币池生成器

版本A (固定33): 生产冻结的固定33币池
版本B (动态33): 每天/每周期从全市场选 Top33 (上市>1年 + 成交量过滤 + 流动性排序)
版本C (Hybrid): 固定基础池 + 定期替换弱币(90天成交量下降/波动降低)为市场强势币
"""
import os, json, pickle, datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# 生产固定33池 (v1_final_spec.md 冻结) — 用OKX能拉到合约数据的
FROZEN_33 = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB', 'ADA', 'AVAX', 'LINK',
             'BCH', 'LTC', 'ZEC', 'SUI', 'TAO', 'XLM', 'NEAR', 'WLD', 'INJ',
             'FIL', 'HBAR', 'TRX', 'ONDO', 'ENA', 'UNI', 'HYPE', 'DOT', 'APT',
             'ARB', 'OP', 'ATOM', 'NEIRO', 'GALA', 'PEPE', 'WIF']
# 注意: 冻结池是34个 (BACKUP), 但 v1_final_spec 表是33币含1000PEPE/TON/FIDA等
# 这里采用生产 BACKUP 34币作为"固定池"参照

def load_coin(sym):
    p = os.path.join(DATA_DIR, f'ohlcv_{sym}.pkl')
    if not os.path.exists(p):
        return None
    with open(p, 'rb') as f:
        bars = pickle.load(f)
    # bars: [[ts,o,h,l,c,v], ...]
    d = {
        'h': [b[2] for b in bars], 'l': [b[3] for b in bars],
        'c': [b[4] for b in bars], 'v': [b[5] for b in bars],
        't': [b[0] for b in bars]
    }
    return d

def load_all_available():
    """加载所有已下载币, 返回 {sym: data}"""
    out = {}
    for fn in os.listdir(DATA_DIR):
        if fn.startswith('ohlcv_') and fn.endswith('.pkl'):
            sym = fn[len('ohlcv_'):-4]
            d = load_coin(sym)
            if d:
                out[sym] = d
    return out

# ============ 版本A: 固定池 ============
def fixed_pool(all_coins):
    """固定池: 生产BACKUP中在数据里存在的币"""
    pool = [c for c in FROZEN_33 if c in all_coins]
    return pool

# ============ 版本B: 动态池 ============
def compute_vol_liquidity(d, start_ts):
    """计算某币在start_ts时刻的成交量均值和流动性(最近200根均价*量)"""
    # 找到 start_ts 之前的数据
    ts = d['t']
    idxs = [i for i, t in enumerate(ts) if t < start_ts]
    if len(idxs) < 200:
        return None, None
    # 用最近90根算成交量均值
    recent = idxs[-90:]
    vol_avg = sum(d['v'][i] for i in recent) / len(recent)
    # 流动性 = 最近200根 价格*量 均值
    recent200 = idxs[-200:]
    liq = sum(d['c'][i] * d['v'][i] for i in recent200) / len(recent200)
    return vol_avg, liq

def listed_before(d, start_ts, min_years=1.0):
    """检查该币数据在start_ts前是否足够 (上市>1年 = 至少min_years*365*6根4H)"""
    ts = d['t']
    earliest = ts[0] if ts else None
    if earliest is None:
        return False
    # 数据最早时间距start_ts是否>1年
    return (start_ts - earliest) >= min_years * 365 * 24 * 3600 * 1000

def dynamic_pool(all_coins, start_ts, top_n=33, min_years=1.0):
    """动态池: 全市场 -> 上市>1年 -> 成交量过滤(>全市场P30) -> 流动性排序Top33"""
    candidates = []
    for sym, d in all_coins.items():
        if not listed_before(d, start_ts, min_years):
            continue
        vol_avg, liq = compute_vol_liquidity(d, start_ts)
        if vol_avg is None or liq is None or liq <= 0:
            continue
        candidates.append((sym, vol_avg, liq))
    if not candidates:
        return []
    # 成交量过滤: 取全部候选成交量中位数
    vols = sorted(c[1] for c in candidates)
    vol_cutoff = vols[len(vols) // 2]
    filtered = [c for c in candidates if c[1] >= vol_cutoff]
    # 流动性排序 (取Top N)
    filtered.sort(key=lambda c: c[2], reverse=True)
    return [c[0] for c in filtered[:top_n]]

# ============ 版本C: Hybrid (固定池+动态替换) ============
def hybrid_pool(all_coins, start_ts, fixed_base, top_n=33, weak_days=90):
    """Hybrid: 固定基础池 + 检测弱币(90天成交量下降/波动降低) 替换为市场强势币"""
    # 1. 从固定池开始
    pool = [c for c in fixed_base if c in all_coins]
    # 2. 检测每个池内币是否弱
    weak = []
    for sym in pool:
        d = all_coins[sym]
        ts = d['t']
        idxs = [i for i, t in enumerate(ts) if t < start_ts]
        if len(idxs) < 90:
            continue
        # 前90天 vs 近90天 成交量
        recent = idxs[-90:]
        older = idxs[-180:-90]
        recent_vol = sum(d['v'][i] for i in recent) / 90
        older_vol = sum(d['v'][i] for i in older) / 90 if older else recent_vol
        vol_change = recent_vol / older_vol if older_vol > 0 else 1.0
        # 波动降低 (ATR下降)
        atr_recent = _atr(d, recent)
        atr_older = _atr(d, older) if older else atr_recent
        atr_change = atr_recent / atr_older if atr_older > 0 else 1.0
        # 弱 = 成交量下降>40% 或 波动降低>40%
        if vol_change < 0.6 or atr_change < 0.6:
            weak.append(sym)
    # 3. 用市场强势币替换弱币
    if weak:
        # 从动态候选里找不在池中的强势币
        strong = dynamic_pool(all_coins, start_ts, top_n=len(weak) * 2 + 10)
        strong = [s for s in strong if s not in pool]
        for i, w in enumerate(weak):
            if i < len(strong):
                pool.remove(w)
                pool.append(strong[i])
    return pool

def _atr(d, idxs):
    if len(idxs) < 2:
        return 0.0
    trs = []
    for i in idxs:
        if i == 0:
            continue
        h, l, pc = d['h'][i], d['l'][i], d['c'][i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0
