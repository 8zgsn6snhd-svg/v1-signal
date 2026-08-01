# -*- coding: utf-8 -*-
"""V1 Dynamic回测 - 数据下载脚本
从OKX拉取全市场USDT永续4H K线 (2023-01-01 ~ 2026-01-01)
筛选: 2025-01-01前上市的币 (回测窗口内某时点满足"上市>1年")
6线程并行下载, 429指数退避
保存: data/ohlcv_{coin}.pkl, data/universe.json
"""
import os, time, json, requests, datetime, pickle
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

START = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
END   = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
LIST_CUTOFF = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
BAR = '4H'
MAX_PAGES = 85
THREADS = 6
lock = __import__('threading').Lock()
stats = {'ok': 0, 'skip': 0, 'fail': 0}

def get_insts():
    r = requests.get('https://www.okx.com/api/v5/public/instruments',
                     params={'instType': 'SWAP'}, timeout=20)
    j = r.json()
    if j['code'] != '0':
        raise RuntimeError('instruments: ' + j.get('msg', ''))
    out = []
    for i in j['data']:
        if i['settleCcy'] == 'USDT' and i['ctType'] == 'linear':
            if int(i['listTime']) < int(LIST_CUTOFF.timestamp() * 1000):
                out.append(i['instId'])
    return sorted(out)

def fetch_one(inst):
    rows = {}
    after = None
    for page in range(MAX_PAGES):
        params = {'instId': inst, 'bar': BAR, 'limit': '100'}
        if after:
            params['after'] = str(after)
        data = None
        for attempt in range(5):
            try:
                r = requests.get('https://www.okx.com/api/v5/market/history-candles',
                                 params=params, timeout=20)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1) + 2)
                    continue
                j = r.json()
                if j['code'] == '0':
                    data = j.get('data', [])
                    break
                time.sleep(1 + attempt)
            except Exception:
                time.sleep(1 + attempt)
        if not data:
            return inst, None, 'FAIL'
        for c in data:
            rows[int(c[0])] = [float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
        if len(data) < 100:
            break
        after = int(data[-1][0])
        if after <= int(START.timestamp() * 1000):
            break
        time.sleep(0.12)
    out = []
    s0 = int(START.timestamp() * 1000)
    e0 = int(END.timestamp() * 1000)
    for ts in sorted(rows):
        if s0 <= ts < e0:
            out.append([ts] + rows[ts])
    coin = inst.replace('-USDT-SWAP', '')
    if len(out) >= 800:
        with open(os.path.join(DATA_DIR, f'ohlcv_{coin}.pkl'), 'wb') as f:
            pickle.dump(out, f)
        with lock:
            stats['ok'] += 1
        return coin, len(out), 'OK'
    else:
        with lock:
            stats['skip'] += 1
        return coin, len(out), 'SKIP'

def main():
    insts = get_insts()
    print(f'候选币: {len(insts)}个 (2025-01前上市)')
    with open(os.path.join(DATA_DIR, 'universe.json'), 'w') as f:
        json.dump({'insts': insts, 'start': START.isoformat(),
                   'end': END.isoformat(), 'bar': BAR}, f)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = [ex.submit(fetch_one, inst) for inst in insts]
        done = 0
        for fut in as_completed(futs):
            coin, n, st = fut.result()
            done += 1
            if st == 'OK':
                print(f'[{done}/{len(insts)}] {coin}: {n}根 OK')
            else:
                print(f'[{done}/{len(insts)}] {coin}: {n}根 {st}')
            if done % 30 == 0:
                print(f'  ... 进度{done}/{len(insts)} 耗时{(time.time()-t0)/60:.1f}min '
                      f'OK{stats["ok"]} SKIP{stats["skip"]}')
    print(f'\n完成: OK{stats["ok"]} SKIP{stats["skip"]} 耗时{(time.time()-t0)/60:.1f}min')

if __name__ == '__main__':
    main()
