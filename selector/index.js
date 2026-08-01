// V1-SELECTOR-DYNAMIC-V2 — 每天 02:00 UTC
// OKX全市场扫描 → 上市>1年 → 成交量过滤 → 流动性排序 → Top33
// 保留固定33 BACKUP fallback, KV pool格式兼容 {ts,version,coins,insts}
const VERSION='SELECTOR-DYNAMIC-V2';
const TOP_N=33;
const MIN_YEARS=1.0;      // 上市>1年
const YEAR_MS=365*24*3600*1000;
// 固定池 BACKUP fallback (V1.8冻结34币)
const BACKUP=['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK',
  'BCH','LTC','ZEC','SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR',
  'TRX','ONDO','ENA','UNI','HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF'];

const OKX_KEY=typeof OKX_API_KEY!=='undefined'?OKX_API_KEY:'';
const OKX_SEC=typeof OKX_SECRET_KEY!=='undefined'?OKX_SECRET_KEY:'';
const OKX_PHR=typeof OKX_PASSPHRASE!=='undefined'?OKX_PASSPHRASE:'';

async function okxGet(path){
  // OKX签名请求 (避免Cloudflare出口IP被公共API限流429)
  // 429退避重试 (最多4次)
  let lastErr;
  const delays=[2000,4000,8000,16000]; // 加长退避: 应对OKX对CF IP的限流窗口
  for(let r=0;r<delays.length;r++){
    if(r>0)await new Promise(w=>setTimeout(w,delays[r-1]+Math.random()*1000));
    try{
      const ts=new Date().toISOString().slice(0,19)+'Z';
      const msg=ts+'GET'+path;
      const e=new TextEncoder();
      const k=await crypto.subtle.importKey('raw',e.encode(OKX_SEC),{name:'HMAC',hash:'SHA-256'},false,['sign']);
      const s=new Uint8Array(await crypto.subtle.sign('HMAC',k,e.encode(msg)));
      const sign=btoa(String.fromCharCode(...s));
      const resp=await fetch('https://www.okx.com'+path,{
        headers:{'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CF-Worker',
          'OK-ACCESS-KEY':OKX_KEY,'OK-ACCESS-SIGN':sign,
          'OK-ACCESS-TIMESTAMP':ts,'OK-ACCESS-PASSPHRASE':OKX_PHR},
        signal:AbortSignal.timeout(15000)});
      if(!resp.ok){
        if(resp.status===429){lastErr=Error('H429');continue;}
        throw Error('H'+resp.status);
      }
      const j=await resp.json();
      if(j.code!=='0'){lastErr=Error('C'+j.code);continue;}
      return j.data||[];
    }catch(e){
      if(e.message==='H429'){lastErr=e;continue;}
      throw e;
    }
  }
  throw lastErr||Error('MAX_RETRY');
}

// ============ 动态选币 ============
// 上市时间缓存 (KV, 避免每次请求instruments; 7天刷新一次)
async function getListTimes(){
  // 先读缓存
  try{
    const cached=await V1_POOL.get('listtime_cache');
    if(cached){
      const c=JSON.parse(cached);
      if(Date.now()-c.ts<7*24*3600*1000){
        log('LISTTIME','用缓存 '+Object.keys(c.data).length+'币');
        return c.data;
      }
    }
  }catch(e){}
  // 请求OKX instruments
  const swaps=await okxGet('/api/v5/public/instruments?instType=SWAP');
  const ltmap={};
  for(const i of swaps){
    if(i.settleCcy==='USDT'&&i.ctType==='linear'){
      ltmap[i.instId.replace('-USDT-SWAP','')]=parseInt(i.listTime);
    }
  }
  try{
    await V1_POOL.put('listtime_cache',JSON.stringify({ts:Date.now(),data:ltmap}));
    log('LISTTIME','已缓存 '+Object.keys(ltmap).length+'币');
  }catch(e){}
  return ltmap;
}

async function dynamicSelect(){
  // 1. 上市时间 (缓存) → 上市>1年候选
  const ltmap=await getListTimes();
  const now=Date.now();
  const cutoff=now-MIN_YEARS*YEAR_MS;
  const candidates=[];
  for(const [coin,lt] of Object.entries(ltmap)){
    if(lt>cutoff)continue;              // 上市<1年, 排除
    candidates.push(coin);
  }

  // 2. 全市场24h成交量/价格 → 流动性 (唯一实时请求)
  const tickers=await okxGet('/api/v5/market/tickers?instType=SWAP');
  const tmap={};
  for(const t of tickers)tmap[t.instId]={vol:parseFloat(t.vol24h)||0,price:parseFloat(t.last)||0};

  // 3. 组合候选: 上市>1年 + 有流动性
  const scored=[];
  for(const coin of candidates){
    const inst=coin+'-USDT-SWAP';
    const t=tmap[inst];
    if(!t||t.price<=0)continue;
    const liq=t.vol*t.price;             // 24h流动性 = 成交量*价格
    if(liq<=0)continue;
    scored.push({coin,inst,liq});
  }

  // 4. 成交量过滤: 保留流动性中位数以上
  if(!scored.length)return[];
  scored.sort((a,b)=>a.liq-b.liq);
  const mid=scored[Math.floor(scored.length/2)].liq;
  const filtered=scored.filter(s=>s.liq>=mid);

  // 5. 流动性降序 Top33
  filtered.sort((a,b)=>b.liq-a.liq);
  return filtered.slice(0,TOP_N).map(s=>s.coin);
}

// ============ fallback: 固定池补足 ============
function withFallback(dynCoins){
  const pool=[...dynCoins];
  for(const c of BACKUP){
    if(pool.length>=TOP_N)break;
    if(!pool.includes(c))pool.push(c);
  }
  // 若仍有缺口(理论上不会), 返回已有
  return pool.slice(0,TOP_N);
}

async function run(){
  const ts=Date.now();
  let dynCoins=[],mode='dynamic',lastErr='';
  try{
    dynCoins=await dynamicSelect();
  }catch(e){
    lastErr=e.message;
    console.log('[SELECTOR][ERR] dynamicSelect: '+e.message);
    dynCoins=[];
  }
  if(dynCoins.length<TOP_N*0.6){
    // 动态池严重不足, 全用固定池
    console.log('[SELECTOR][FALLBACK] 动态池不足('+dynCoins.length+'), 用固定池');
    mode='fallback';
    dynCoins=withFallback([]);
  }else{
    dynCoins=withFallback(dynCoins);
  }

  const coins=dynCoins.slice(0,TOP_N);
  const insts=coins.map(c=>c+'-USDT-SWAP');
  const data={ts,version:VERSION,mode,coins,insts};
  if(typeof V1_POOL!=='undefined'){
    await V1_POOL.put('pool',JSON.stringify(data));
  }
  let r='['+VERSION+'] '+new Date(ts).toISOString().slice(0,16).replace('T',' ')+' mode='+mode+(lastErr?' ERR:'+lastErr:'')+'\n';
  r+='选币 '+coins.length+'/'+TOP_N+' OK\n';
  for(let i=0;i<coins.length;i++)r+=coins[i]+' '+insts[i]+'\n';
  return r;
}

async function show(){
  let r='['+VERSION+']\n';
  if(typeof V1_POOL!=='undefined'){
    try{
      const p=await V1_POOL.get('pool');
      if(p){
        const pp=JSON.parse(p);
        r+='池:'+pp.coins.length+'币 mode='+(pp.mode||'?')+' 更新:'+new Date(pp.ts).toISOString().slice(0,10)+'\n';
        for(const c of pp.coins)r+=c+'\n';
        return r;
      }
    }catch(e){}
  }
  r+='无池 /cron触发';
  return r;
}

// /debug 诊断: 直接跑dynamicSelect, 返回详细错误
async function debug(e){
  const out={version:VERSION,time:new Date().toISOString(),
    has_key:!!OKX_KEY,has_sec:!!OKX_SEC,has_phr:!!OKX_PHR};
  try{
    const swaps=await okxGet('/api/v5/public/instruments?instType=SWAP');
    out.instruments=swaps.length;
    const now=Date.now(),cutoff=now-365*24*3600*1000;
    const cands=swaps.filter(i=>i.settleCcy==='USDT'&&i.ctType==='linear'&&parseInt(i.listTime)<=cutoff);
    out.candidates=cands.length;
    const tickers=await okxGet('/api/v5/market/tickers?instType=SWAP');
    out.tickers=tickers.length;
    const tmap={};for(const t of tickers)tmap[t.instId]=t;
    let scored=0;
    for(const c of cands)if(tmap[c.instId])scored++;
    out.scored=scored;
    out.status='ok';
  }catch(err){
    out.status='error';
    out.error=err.message;
    out.stack=err.stack;
  }
  return new Response(JSON.stringify(out),{headers:{'Content-Type':'application/json'}});
}

addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(u.pathname==='/cron')return e.respondWith(run().then(r=>new Response(r)));
  if(u.pathname==='/debug')return e.respondWith(debug(e));
  e.respondWith(show().then(r=>new Response(r)));
});
addEventListener('scheduled',e=>e.waitUntil(run().catch(er=>console.log(er.message))));
