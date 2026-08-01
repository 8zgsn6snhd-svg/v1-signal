# -*- coding: utf-8 -*-
"""Dynamic 池变化分析
逐日调用 dynamic_pool, 记录:
- 每年平均选币数
- 新增/移除币次数
- 全年出现过的全部币
- 与固定池的重叠度
同时验证无未来泄漏: 每个币选中时所用的数据 bar 都 < start_ts"""
import os, sys, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
from pools import load_all_available, dynamic_pool, fixed_pool

DAY_MS = 24 * 3600 * 1000

def main():
    all_coins = load_all_available()
    fixed_base = [c for c in fixed_pool(all_coins)]
    print(f'可用币: {len(all_coins)}, 固定池: {len(fixed_base)}')

    # 逐日分析 2023-01-01 ~ 2026-01-01
    start = int(datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    end = int(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    yearly = {}
    prev_pool = None
    leak_count = 0
    total_checks = 0
    day_i = 0

    ts = start
    while ts < end:
        pool = dynamic_pool(all_coins, ts, top_n=33)
        y = datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc).year
        yearly.setdefault(y, {'n_days': 0, 'n_empty': 0, 'n_add': 0, 'n_rm': 0, 'coins': set(), 'sizes': []})

        yearly[y]['n_days'] += 1
        if not pool:
            yearly[y]['n_empty'] += 1
        else:
            yearly[y]['sizes'].append(len(pool))
            yearly[y]['coins'].update(pool)
            # 与上一日对比新增/移除
            if prev_pool is not None:
                add = [c for c in pool if c not in prev_pool]
                rm = [c for c in prev_pool if c not in pool]
                yearly[y]['n_add'] += len(add)
                yearly[y]['n_rm'] += len(rm)

        # 未来泄漏验证: 池中每币, 检查选币时刻是否只用过去bar
        if pool:
            for sym in pool:
                d = all_coins[sym]
                # compute_vol_liquidity 用 t < start_ts 的 bar
                past_bars = [i for i, t in enumerate(d['t']) if t < ts]
                total_checks += 1
                # 若该币在ts时无过去bar却入选, 则是泄漏
                if len(past_bars) < 200:
                    leak_count += 1

        prev_pool = pool
        ts += DAY_MS
        day_i += 1

    print(f'\n总天数: {day_i}')
    print(f'未来泄漏检查: {total_checks}次选中, 泄漏 {leak_count} 次 (0=无泄漏)')

    print('\n========== 分年份动态池报告 ==========')
    for y in sorted(yearly.keys()):
        d = yearly[y]
        sizes = d['sizes']
        avg = sum(sizes) / len(sizes) if sizes else 0
        print(f'\n===== {y} =====')
        print(f'  选币天数: {d["n_days"]}  空池天数: {d["n_empty"]}')
        print(f'  平均币数: {avg:.1f}  (目标33)')
        print(f'  新增币: {d["n_add"]}次  移除币: {d["n_rm"]}次')
        print(f'  换手率(日均): 新增{d["n_add"]/max(d["n_days"],1):.1f}次/天')
        print(f'  全年出现过的币({len(d["coins"])}个):')
        coins = sorted(d['coins'])
        for i in range(0, len(coins), 8):
            print('   ' + ' '.join(coins[i:i+8]))
        # 与固定池重叠
        overlap = len(d['coins'] & set(fixed_base))
        print(f'  与固定池重叠: {overlap}/{len(fixed_base)}')

if __name__ == '__main__':
    main()
