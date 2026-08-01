# -*- coding: utf-8 -*-
"""监控下载进度, 当所有候选币下载完成或进程结束时退出"""
import os, time, json, sys

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
universe = os.path.join(DATA_DIR, 'universe.json')

def main():
    with open(universe) as f:
        total = len(json.load(f)['insts'])
    # 等待下载进程结束 + 数据完整
    while True:
        got = len([f for f in os.listdir(DATA_DIR) if f.startswith('ohlcv_') and f.endswith('.pkl')])
        # 检查python进程是否还在跑
        import subprocess
        r = subprocess.run(['tasklist'], capture_output=True, text=True)
        py_running = 'python' in r.stdout.lower()
        pct = got / total * 100
        print(f'进度: {got}/{total} ({pct:.0f}%) python={'running' if py_running else 'STOPPED'}', flush=True)
        if not py_running:
            print('下载进程已结束', flush=True)
            break
        time.sleep(120)
    print('DONE', flush=True)

if __name__ == '__main__':
    main()
