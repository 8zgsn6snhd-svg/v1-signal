# -*- coding: utf-8 -*-
"""V1 Dynamic回测 - 数据下载脚本 (异步并发版)

从OKX拉取全市场USDT永续4H K线 (2023-01-01 ~ 2026-01-01)
筛选: 2025-01-01前上市的币 (回测窗口内某时点满足"上市>1年")

特性:
- aiohttp 异步并发, 最大并发10
- 保留OKX限流保护: 429指数退避, 全局速率限制 (每请求间隔)
- 单币失败自动重试 (每页重试5次)
- 断点续传: 已下载的币自动跳过, 不重复请求
- 实时进度: 每完成一个币打印进度
- 数据格式不变: data/ohlcv_{coin}.pkl, [ts,o,h,l,c,v] 从旧到新
"""
import os, time, json, requests, datetime, pickle, asyncio, aiohttp

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

START = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
END   = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
LIST_CUTOFF = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
BAR = '4H'
MAX_PAGES = 85
CONCURRENCY = 10
MIN_BARS = 800
PAGE_DELAY = 0.05    # 每页间最小间隔, 避免过载OKX

# ============ 同步获取币列表 ============
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

# ============ 单币异步拉取 ============
async def fetch_one(session, inst):
    """拉取单币全量历史, 返回 coin, bars(list), status"""
    rows = {}
    after = None
    for page in range(MAX_PAGES):
        params = {'instId': inst, 'bar': BAR, 'limit': '100'}
        if after:
            params['after'] = str(after)
        data = None
        for attempt in range(5):
            try:
                async with session.get(
                    'https://www.okx.com/api/v5/market/history-candles',
                    params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(1.5 * (attempt + 1) + 2)
                        continue
                    if resp.status != 200:
                        await asyncio.sleep(1 + attempt)
                        continue
                    j = await resp.json()
                    if j.get('code') == '0':
                        data = j.get('data', [])
                        break
                    await asyncio.sleep(1 + attempt)
            except asyncio.TimeoutError:
                await asyncio.sleep(1 + attempt)
            except Exception:
                await asyncio.sleep(1 + attempt)
        if not data:
            return inst.replace('-USDT-SWAP', ''), None, 'PAGE_FAIL'
        for c in data:
            rows[int(c[0])] = [float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
        if len(data) < 100:
            break
        after = int(data[-1][0])
        if after <= int(START.timestamp() * 1000):
            break
        await asyncio.sleep(PAGE_DELAY)

    out = []
    s0 = int(START.timestamp() * 1000)
    e0 = int(END.timestamp() * 1000)
    for ts in sorted(rows):
        if s0 <= ts < e0:
            out.append([ts] + rows[ts])
    coin = inst.replace('-USDT-SWAP', '')
    if len(out) >= MIN_BARS:
        return coin, out, 'OK'
    else:
        return coin, len(out), 'SKIP'

# ============ 主控: 并发 + 断点续传 ============
async def main():
    insts = get_insts()
    print(f'候选币: {len(insts)}个 (2025-01前上市)')
    # 断点续传: 已下载的币跳过
    done = set()
    for fn in os.listdir(DATA_DIR):
        if fn.startswith('ohlcv_') and fn.endswith('.pkl'):
            done.add(fn[6:-4])
    todo = [i for i in insts if i.replace('-USDT-SWAP', '') not in done]
    print(f'已下载: {len(done)}, 待下载: {len(todo)}')
    if not todo:
        print('全部已完成!')
        return

    ok_count, skip_count = 0, 0
    t0 = time.time()
    # 关键: aiohttp默认用aiodns异步解析, 在本机无法联系DNS (DNS resolution failed)
    # 改用 ThreadedResolver (走系统getaddrinfo, 与requests一致), 避免DNS失败
    resolver = aiohttp.resolver.ThreadedResolver()
    conn = aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=CONCURRENCY,
                                resolver=resolver)
    async with aiohttp.ClientSession(connector=conn) as session:
        # 信号量控制并发
        sem = asyncio.Semaphore(CONCURRENCY)
        results = {}
        async def worker(inst):
            nonlocal ok_count, skip_count
            async with sem:
                coin, bars, status = await fetch_one(session, inst)
                return coin, bars, status
        # 分批提交, 每批实时打印
        for i in range(0, len(todo), CONCURRENCY):
            batch = todo[i:i + CONCURRENCY]
            batch_res = await asyncio.gather(*[worker(inst) for inst in batch])
            for coin, bars, status in batch_res:
                if status == 'OK':
                    with open(os.path.join(DATA_DIR, f'ohlcv_{coin}.pkl'), 'wb') as f:
                        pickle.dump(bars, f)
                    ok_count += 1
                    tag = 'OK'
                elif status == 'SKIP':
                    skip_count += 1
                    tag = f'SKIP({bars}根)'
                else:
                    skip_count += 1
                    tag = 'FAIL'
                el = time.time() - t0
                pct = (i + 1) / len(todo) * 100
                print(f'[{i+1}/{len(todo)} {pct:.0f}%] {coin}: {tag} 累计OK={ok_count} '
                      f'耗时{el/60:.1f}min', flush=True)

    print(f'\n完成: OK={ok_count} SKIP/FAIL={skip_count} 总耗时{(time.time()-t0)/60:.1f}min')

if __name__ == '__main__':
    asyncio.run(main())
