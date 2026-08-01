# -*- coding: utf-8 -*-
"""回测指标计算: 总收益/年化/最大回撤/PF/交易数/连亏/分年份表现"""
import math, datetime

def compute_metrics(equity, trades, start_ts, end_ts, initial=10000):
    """equity: [(ts, balance)], trades: list of trade dicts"""
    final = equity[-1][1] if equity else initial
    total_ret = (final / initial - 1) * 100

    # 年化 (按实际时间跨度)
    span_years = max((end_ts - start_ts) / (365 * 24 * 3600 * 1000), 0.1)
    if final > 0 and initial > 0:
        annual = ((final / initial) ** (1 / span_years) - 1) * 100
    else:
        annual = -100

    # 最大回撤
    peak = -1e18
    max_dd = 0.0
    for _, v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd

    # PF
    gross_profit = sum(max(0, t['pnl']) for t in trades)
    gross_loss = sum(max(0, -t['pnl']) for t in trades)
    pf = gross_profit / gross_loss if gross_loss > 0 else 99.9

    # 交易统计
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    # 连续亏损 (按时间排序)
    trades_sorted = sorted(trades, key=lambda t: t['exit_ts'])
    max_consec_loss = 0
    cur = 0
    for t in trades_sorted:
        if t['pnl'] <= 0:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    # 平均R
    avg_R = sum(t['R_multiple'] for t in trades) / len(trades) if trades else 0

    # 分年份
    yearly = {}
    for t in trades_sorted:
        y = datetime.datetime.fromtimestamp(t['exit_ts'] / 1000, datetime.timezone.utc).year
        yearly.setdefault(y, {'pnl': 0, 'n': 0})
        yearly[y]['pnl'] += t['pnl']
        yearly[y]['n'] += 1

    return {
        'total_ret': total_ret, 'annual': annual, 'max_dd': max_dd,
        'pf': pf, 'trades': len(trades), 'win_rate': win_rate,
        'max_consec_loss': max_consec_loss, 'avg_R': avg_R,
        'final_balance': final, 'yearly': yearly
    }
