# -*- coding: utf-8 -*-
"""V1 三版本对比报告生成器
输出完整对比: 总收益/年化/回撤/PF/交易数/连亏/分年份/决定性分析"""
import os, sys, json, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
from metrics import compute_metrics

RESULTS_FILE = os.path.join(os.path.dirname(__file__), 'results', 'comparison_results.json')
REPORT_FILE = os.path.join(os.path.dirname(__file__), 'results', 'comparison_report.md')

def fmt_year(yearly):
    """分年份格式化"""
    lines = []
    for y in sorted(yearly.keys()):
        d = yearly[y]
        lines.append(f'{y}: {d["pnl"]:+,.0f}U ({d["n"]}笔)')
    return '\n'.join(lines)

def main():
    with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
        results = json.load(f)

    # 决定性分析
    rows = []
    for name, res in results.items():
        m = res['metrics']
        rows.append({
            'name': name, 'mode': res['mode'],
            'ret': m['total_ret'], 'annual': m['annual'], 'dd': m['max_dd'],
            'pf': m['pf'], 'n': m['trades'], 'wr': m['win_rate'],
            'consec': m['max_consec_loss'], 'avgR': m['avg_R'], 'yearly': m['yearly']
        })

    # 排序: 按收益
    rows.sort(key=lambda r: r['ret'], reverse=True)
    best = rows[0]

    md = []
    md.append('# V1 三版本选币回测对比报告')
    md.append('')
    md.append(f'**回测窗口**: 2023-01-01 ~ 2026-01-01 (3年)')
    md.append(f'**初始资金**: 10000U')
    md.append(f'**数据**: OKX USDT永续合约 4H K线 (145币全市场)')
    md.append(f'**策略**: V1 (三重ST C信号 + 成交量过滤 + ST距离≤3% + BTC只退 + 3仓 + 固定风险1% + 手续费0.05% + 滑点0.03%)')
    md.append(f'**只改变**: 币池生成方式')
    md.append('')

    md.append('## 核心指标对比')
    md.append('')
    md.append('| 版本 | 总收益 | 年化 | 最大回撤 | PF | 交易数 | 胜率 | 连续亏损 | 平均R |')
    md.append('|:-----|:-----:|:----:|:-------:|:--:|:-----:|:----:|:------:|:-----:|')
    for r in rows:
        star = ' 🥇' if r is best else ''
        md.append(f'| {r["name"]} | {r["ret"]:+.1f}% | {r["annual"]:+.1f}% | {r["dd"]:.1f}% | '
                  f'{r["pf"]:.2f} | {r["n"]} | {r["wr"]:.1f}% | {r["consec"]} | {r["avgR"]:.2f} |{star}')
    md.append('')

    md.append('## 分年份表现')
    md.append('')
    for r in rows:
        md.append(f'### {r["name"]}')
        md.append('')
        md.append(fmt_year(r['yearly']))
        md.append('')

    md.append('## 决定性分析')
    md.append('')
    md.append(f'### 结论: **{best["name"]} 最优**')
    md.append('')
    md.append(f'- **{best["name"]}**: 总收益 {best["ret"]:+.1f}%, PF {best["pf"]:.2f}, 回撤 {best["dd"]:.1f}%')
    md.append('')
    md.append('### 决策规则 (收益提升 + PF提高 + 回撤不恶化 + 年份稳定 才替换)')
    md.append('')
    for r in rows:
        if r is best:
            continue
        ret_diff = best['ret'] - r['ret']
        pf_diff = best['pf'] - r['pf']
        dd_diff = best['dd'] - r['dd']
        md.append(f'- **vs {r["name"]}**: 收益 {ret_diff:+.1f}%, PF {pf_diff:+.2f}, 回撤 {"改善" if dd_diff<0 else "恶化"} {abs(dd_diff):.1f}%')
    md.append('')
    md.append('### 稳健性检查')
    md.append('')
    for r in rows:
        yrs = r['yearly']
        positive_years = sum(1 for y in yrs.values() if y['pnl'] > 0)
        md.append(f'- **{r["name"]}**: {positive_years}/{len(yrs)} 年盈利')

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    print(f'报告已生成: {REPORT_FILE}')

if __name__ == '__main__':
    main()
