// V1-DATA-C-2.0 — 读KV pool动态拉币 + 500ms间隔 + 单币3次重试(1s/3s/8s) + 失败分类
// 从 KV pool.coins 读动态池, 按切片分配: C取后1/3
const POOL_KVID='7d4e8decec9849e8becab243a3d4de15';   // V1_POOL 命名空间
const KVKEY='ohlcv_C';
const KVID='1074343ba32f4d43be99455ff88cfecb';
const AID='503d56d255b8bfd89e71160f3f98f8df';
const CF_TOK=typeof CF_API_TOKEN!=='undefined'?CF_API_TOKEN:'';
const NAME='DATA-C';
// 固定fallback (V1.8冻结34币 尾部)
const FIXED_COINS=['HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF'];
const SLICE_START=24, SLICE_END=33;   // C拉 24-33

function log(t,m){console.log('['+NAME+']['+t+'] '+m);}
function cls(e){const m=e&&e.message?e.message:'';if(m==='RATE_LIMIT')return'RATE_LIMIT';if(m==='TIMEOUT')return'TIMEOUT';if(m==='SYMBOL_ERROR')return'SYMBOL_ERROR';return'API_ERROR';}

async function kvR(key,kvid){
  if(!CF_TOK){log('KV','NO_CF_TOKEN');return null;}
  try{
    const r=await fetch('https://api.cloudflare.com/client/v4/accounts/'+AID+'/storage/kv/namespaces/'+kvid+'/values/'+key,
      {headers:{'Authorization':'Bearer '+CF_TOK}});
    if(!r.ok){log('KV',key+' HTTP'+r.status);return null;}
    return await r.json();
  }catch(e){return null;}
}

// 读动态池, 返回本组应拉的币
async function getMyCoins(){
  const pool=await kvR('pool',POOL_KVID);
  if(pool&&pool.coins&&pool.coins.length>=20){
    log('POOL','动态池 '+pool.coins.length+'币 mode='+(pool.mode||'?')+' 时间:'+pool.time);
    const slice=pool.coins.slice(SLICE_START,SLICE_END+1);
    log('POOL','本组拉取 '+slice.length+'币: '+slice.join(','));
    return slice;
  }
  log('POOL','fallback固定池 '+FIXED_COINS.length+'币');
  return FIXED_COINS;
}

async function okxF(path){
  const key=typeof OKX_API_KEY!=='undefined'?OKX_API_KEY:'';
  const sec=typeof OKX_SECRET_KEY!=='undefined'?OKX_SECRET_KEY:'';
  const phr=typeof OKX_PASSPHRASE!=='undefined'?OKX_PASSPHRASE:'';
  if(!key){log('AUTH','NO_KEY');throw Error('NO_OKX');}
  let lastErr;
  for(let r=0;r<3;r++){
    if(r>0){
      const wait=1000*Math.pow(2,r-1)+Math.random()*1000;
      log('RETRY_429','第'+r+'次重试 等待'+Math.round(wait)+'ms');
      await new Promise(w=>setTimeout(w,wait));
    }
    try{
      const ts=new Date().toISOString().slice(0,19)+'Z';
      const msg=ts+'GET'+path;
      const e=new TextEncoder();
      const k=await crypto.subtle.importKey('raw',e.encode(sec),{name:'HMAC',hash:'SHA-256'},false,['sign']);
      const s=new Uint8Array(await crypto.subtle.sign('HMAC',k,e.encode(msg)));
      const sign=btoa(String.fromCharCode(...s));
      const rp=await fetch('https://www.okx.com'+path,{
        headers:{'User-Agent':'CF','OK-ACCESS-KEY':key,'OK-ACCESS-SIGN':sign,
                 'OK-ACCESS-TIMESTAMP':ts,'OK-ACCESS-PASSPHRASE':phr},
        signal:AbortSignal.timeout(12000)});
      if(!rp.ok){
        if(rp.status===429){lastErr=Error('RATE_LIMIT');continue;}
        log('HTTP',path+' '+rp.status);throw Error('HTTP'+rp.status);
      }
      const j=await rp.json();
      if(j.code!=='0'){
        if(j.code==='51001')throw Error('SYMBOL_ERROR');
        log('CODE',path+' '+j.code+' '+j.msg);throw Error('API_ERROR');
      }
      return j.data||[];
    }catch(e){
      if(e.name==='TimeoutError')throw Error('TIMEOUT');
      if(e.message==='RATE_LIMIT'){lastErr=e;continue;}
      throw e;
    }
  }
  throw lastErr||Error('MAX_RETRY');
}
async function kvW(key,val){
  if(!CF_TOK){log('KV','NO_CF_TOKEN');return;}
  try{await fetch('https://api.cloudflare.com/client/v4/accounts/'+AID+'/storage/kv/namespaces/'+KVID+'/values/'+key,
    {method:'PUT',headers:{'Authorization':'Bearer '+CF_TOK,'Content-Type':'application/json'},body:JSON.stringify(val)});
  }catch(e){log('KV','PUT_FAIL:'+e.message);}
}
async function run(){
  // 启动随机jitter 0-45秒
  const jitter=Math.random()*45000;
  if(jitter>2000)log('JITTER','等待'+(jitter/1000).toFixed(1)+'秒');
  await new Promise(w=>setTimeout(w,jitter));
  const st=Date.now();log('START','');
  const COINS=await getMyCoins();
  log('DATA_C_START','time='+new Date().toISOString());
  log('DATA_C_START','请求币数量: '+COINS.length+' 组='+KVKEY);
  const kd={};let fail=[]; // fail=[{c,reason}]
  await kvW(KVKEY,{status:'busy',ts:Date.now()});
  for(const c of COINS){
    const reqSt=Date.now();
    log('COIN_START',c+':');
    try{
      const d=await okxF('/api/v5/market/candles?instId='+c+'-USDT-SWAP&bar=4H&limit=200');
      const reqT=Date.now()-reqSt;
      if(!d||d.length<50){
        const len=d?d.length:0;
        log('COIN_END',c+' FAILED EMPTY_DATA candles='+len+' time='+reqT+'ms');
        fail.push({c,reason:'EMPTY_DATA'});
        continue;
      }
      const dr=d.reverse();
      kd[c]={h:dr.map(k=>+k[2]),l:dr.map(k=>+k[3]),c:dr.map(k=>+k[4]),v:dr.map(k=>+k[5]),t:dr.map(k=>+k[0])};
      const close=dr[dr.length-1]?.[4];
      log('COIN_END',c+' success HTTP=200 OKX=0 candles='+d.length+' close='+close+' time='+reqT+'ms');
    }catch(e){
      const reason=cls(e);
      const reqT=Date.now()-reqSt;
      log('COIN_END',c+' FAILED '+reason+' error='+e.message+' time='+reqT+'ms');
      fail.push({c,reason});
    }
    // 请求间隔 500ms + 随机100-300ms
    if(c!==COINS[COINS.length-1])await new Promise(w=>setTimeout(w,500+Math.random()*300));
  }
  // 单币独立重试 最多3轮, 间隔 1s/3s/8s
  const retryDelay=[1000,3000,8000];
  for(let at=0;at<3;at++){
    if(!fail.length)break;
    log('RETRY','第'+(at+1)+'轮 失败币:'+fail.map(f=>f.c).join(','));
    await new Promise(w=>setTimeout(w,retryDelay[at]));
    const still=[];
    for(const f of fail){
      try{
        log('RETRY_START',f.c);
        const d=await okxF('/api/v5/market/candles?instId='+f.c+'-USDT-SWAP&bar=4H&limit=200');
        if(d&&d.length>50){const dr=d.reverse();
          kd[f.c]={h:dr.map(k=>+k[2]),l:dr.map(k=>+k[3]),c:dr.map(k=>+k[4]),v:dr.map(k=>+k[5]),t:dr.map(k=>+k[0])};
          log('RETRY_OK',f.c+' recovered');
        }else{log('RETRY_FAIL',f.c+' still short bars='+(d?d.length:0));still.push(f);}
      }catch(e){log('RETRY_ERR',f.c+' '+e.message);still.push({c:f.c,reason:cls(e)});}
      if(f!==fail[fail.length-1])await new Promise(w=>setTimeout(w,500+Math.random()*300));
    }
    fail=still;
  }
  const ok=COINS.filter(c=>kd[c]&&kd[c].c).length;
  log('DATA_C_END','success='+ok+'/'+COINS.length+' failed='+fail.length+' total_time='+((Date.now()-st)/1000).toFixed(1)+'秒');
  // KV写入: ohlcv_C 格式
  log('KV_WRITE_START','key='+KVKEY);
  const now=new Date();
  const kvData={status:'ready',time:now.toISOString().slice(0,16).replace('T',' '),success:ok,
    failed:fail.map(f=>f.c),reasons:fail,data:kd,ts:Date.now()};
  await kvW(KVKEY,kvData);
  const kvSize=JSON.stringify(kvData).length;
  log('KV_WRITE_OK','key='+KVKEY+' timestamp='+kvData.time+' size='+kvSize+'bytes');
  log('END','耗时'+(Date.now()-st)+'ms');
  return 'DATA-C '+ok+'/'+COINS.length+' '+(Date.now()-st)+'ms';
}
addEventListener('fetch',e=>e.respondWith(run().then(r=>new Response(r)).catch(er=>new Response('E:'+er.message))));
addEventListener('scheduled',e=>e.waitUntil(run().catch(er=>console.log(er.message))));
