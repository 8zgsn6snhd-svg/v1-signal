# -*- coding: utf-8 -*-
"""验证: Python引擎的ST/C信号 与 生产 signal/index.js 逻辑一致
用同一份数据, 对若干随机bar, 对比两边的C信号判定和方向.
生产侧用node子进程执行JS逻辑."""
import os, sys, pickle, subprocess, json, random

sys.path.insert(0, os.path.dirname(__file__))
from v1_engine import Coin, ST_PARAMS

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# 生产JS逻辑 (复制自 signal/index.js st + an, 输入OHLCV数组)
JS_LOGIC = r"""
const CFG={S1:[6,1.0],S2:[10,2.5],S3:[14,5.0],VOL_FILTER:0.5};
function st(h,l,c,p,m){if(!c||c.length<p)return null;
  const n=c.length,hl=Array(n);for(let i=0;i<n;i++)hl[i]=(h[i]+l[i])/2;
  const tr=Array(n).fill(0);for(let i=1;i<n;i++)tr[i]=Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1]));
  const at=Array(n).fill(0);let s=0;for(let i=0;i<p;i++)s+=tr[i];at[p-1]=s/p;
  for(let i=p;i<n;i++)at[i]=(at[i-1]*(p-1)+tr[i])/p;
  const up=Array(n),lo=Array(n),ln=Array(n),dr=Array(n);
  up[p-1]=hl[p-1]+m*at[p-1];lo[p-1]=hl[p-1]-m*at[p-1];dr[p-1]=1;ln[p-1]=up[p-1];
  for(let i=p;i<n;i++){const u=hl[i]+m*at[i],lw=hl[i]-m*at[i];
    up[i]=(u<up[i-1]||c[i-1]>up[i-1])?u:up[i-1];lo[i]=(lw>lo[i-1]||c[i-1]<lo[i-1])?lw:lo[i-1];
    const x=Math.abs(ln[i-1]-up[i-1])<Math.abs(ln[i-1]-lo[i-1]);
    dr[i]=x?(c[i]>up[i]?-1:1):(c[i]<lo[i]?1:-1);ln[i]=dr[i]===-1?lo[i]:up[i];}
  return{ln,dr};}
function an(cn,h,l,c,vl,bd){const cu=c[c.length-1],ix=c.length-2;
  const s1=st(h,l,c,...CFG.S1),s2=st(h,l,c,...CFG.S2),s3=st(h,l,c,...CFG.S3);
  if(!s1||!s2||!s3||ix<1)return null;const cv=vl[ix];const lb=Math.min(90,ix-1);let av=0;
  for(let j=ix-lb;j<ix;j++)av+=vl[j];av/=lb;
  if(av>0&&cv<av*CFG.VOL_FILTER)return null;
  const d1=s1.dr[ix],d2=s2.dr[ix],d3=s3.dr[ix];
  const cT=(d1===d2&&d2===d3)&&!(s1.dr[ix-1]===s2.dr[ix-1]&&s2.dr[ix-1]===s3.dr[ix-1]);
  const sh=d1===1;let R=0,sp=0;
  if(cT){sp=s1.ln[ix];R=sh?((sp/cu-1)*100):((cu/sp-1)*100);}
  return{cu,ix,cT,R,sh,sp,dm:bd===d1};}
// 输入 JSON: {h:[],l:[],c:[],v:[]}
const input=JSON.parse(process.argv[1]);
const a=an(input.sym,input.h,input.l,input.c,input.v,0);
const s1=st(input.h,input.l,input.c,...CFG.S1);
const dr1=s1?s1.dr[input.c.length-2]:null;
const ln1=s1?s1.ln[input.c.length-2]:null;
console.log(JSON.stringify({cT:a?a.cT:false,R:a?a.R:0,sp:a?a.sp:0,sh:a?a.sh:null,dr1,ln1}));
"""

def run_js(h, l, c, v):
    payload = json.dumps({'sym':'X','h':h,'l':l,'c':c,'v':v})
    r = subprocess.run(['node', '-e', JS_LOGIC, payload], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout.strip())

def verify_coin(sym, window=600, check_bars=50):
    with open(os.path.join(DATA_DIR, f'ohlcv_{sym}.pkl'), 'rb') as f:
        bars = pickle.load(f)
    if len(bars) < window + 50:
        return f'{sym}: 数据不足'
    h = [b[2] for b in bars]; l = [b[3] for b in bars]
    c = [b[4] for b in bars]; v = [b[5] for b in bars]
    coin = Coin(sym, h, l, c, v, [b[0] for b in bars])

    # 取末尾 window 根 (与生产一致: 用末尾判断)
    mismatches = []
    total = 0
    for _ in range(check_bars):
        end = len(c) - random.randint(100, 500)  # 随机截断点
        if end < 200:
            continue
        hh, ll, cc, vv = h[end-200:end], l[end-200:end], c[end-200:end], v[end-200:end]
        js = run_js(hh, ll, cc, vv)
        if js is None:
            continue
        total += 1
        # Python侧: 用同样窗口构造Coin, 取末尾bar判定
        sub_coin = Coin(sym, hh, ll, cc, vv, list(range(len(cc))))
        idx = len(cc) - 2  # 生产用 ix=c.length-2
        py_cT = sub_coin.c_signal(idx)
        py_dr1 = sub_coin.trends[0][idx]
        py_sp = sub_coin.lines[0][idx]
        # 方向语义: 生产 sh=(d1===1)表示dr=1为空头. Python dr同样
        if py_cT != js['cT'] or py_dr1 != js['dr1']:
            mismatches.append((end, py_cT, js['cT'], py_dr1, js['dr1'], py_sp, js['sp']))
    return sym, total, mismatches

def main():
    symbols = ['ADA', 'APT', 'ALGO', 'AAVE'] if os.path.exists(os.path.join(DATA_DIR, 'ohlcv_ADA.pkl')) else []
    # 只测已下载的
    symbols = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if fn.startswith('ohlcv_') and fn.endswith('.pkl'):
            symbols.append(fn[6:-4])
        if len(symbols) >= 4:
            break
    for sym in symbols:
        res = verify_coin(sym)
        if isinstance(res, str):
            print(res)
            continue
        sym_name, total, mismatches = res
        if total == 0:
            print(f'{sym_name}: 无有效测试')
            continue
        print(f'{sym_name}: 测试{total}bar, 不一致{mismatches}')
        if mismatches:
            for m in mismatches[:5]:
                print(f'   MISMATCH end={m[0]} py_cT={m[1]} js_cT={m[2]} py_dr1={m[3]} js_dr1={m[4]} py_sp={m[5]:.6f} js_sp={m[6]:.6f}')
        else:
            print(f'   [OK] C信号和ST1方向 与生产完全一致')

if __name__ == '__main__':
    main()
