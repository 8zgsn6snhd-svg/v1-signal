// V1-DATA-B-1.2 — OKX签名 + 429指数退避 + jitter + KV ready标记
const COINS=['SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR','TRX','ONDO','ENA','UNI'];
const KVID='1074343ba32f4d43be99455ff88cfecb';
const AID='503d56d255b8bfd89e71160f3f98f8df';
const CF_TOK=typeof CF_API_TOKEN!=='undefined'?CF_API_TOKEN:'';
const NAME='DATA-B';
function log(t,m){console.log('['+NAME+']['+t+'] '+m);}

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
        if(rp.status===429){lastErr=Error('H429');continue;}
        log('HTTP',path+' '+rp.status);throw Error('H'+rp.status);
      }
      const j=await rp.json();
      if(j.code!=='0'){log('CODE',path+' '+j.code+' '+j.msg);throw Error('C'+j.code);}
      return j.data||[];
    }catch(e){
      if(e.message==='H429'){lastErr=e;continue;}
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
  // A: 启动随机jitter 0-45秒
  const jitter=Math.random()*45000;
  if(jitter>2000)log('JITTER','等待'+(jitter/1000).toFixed(1)+'秒');
  await new Promise(w=>setTimeout(w,jitter));
  const st=Date.now();log('START','');
  log('DATA_B_START','time='+new Date().toISOString());
  log('DATA_B_START','请求币数量: '+COINS.length);
  const kd={};let fail=[];
  await kvW('data_b',{status:'busy',ts:Date.now()});
  for(const c of COINS){
    const reqSt=Date.now();
    log('COIN_START',c+':');
    try{
      const d=await okxF('/api/v5/market/candles?instId='+c+'-USDT-SWAP&bar=4H&limit=200');
      const reqT=Date.now()-reqSt;
      if(!d||d.length<50){
        const len=d?d.length:0;
        log('COIN_END',c+' FAILED');
        log('COIN_END','  HTTP=200 OKX=0 candles='+len+' time='+reqT+'ms');
        fail.push(c);
        continue;
      }
      const dr=d.reverse();
      kd[c]={h:dr.map(k=>+k[2]),l:dr.map(k=>+k[3]),c:dr.map(k=>+k[4]),v:dr.map(k=>+k[5]),t:dr.map(k=>+k[0])};
      const close=dr[dr.length-1]?.[4];
      log('COIN_END',c+' success HTTP=200 OKX=0 candles='+d.length+' close='+close+' time='+reqT+'ms');
    }catch(e){
      const reqT=Date.now()-reqSt;
      log('COIN_END',c+' FAILED error='+e.message+' time='+reqT+'ms');
      fail.push(c);
    }
    if(c!==COINS[COINS.length-1])await new Promise(w=>setTimeout(w,200+Math.random()*400));
  }
  if(fail.length){log('RETRY','失败币:'+fail.join(','));
    for(const c of fail){try{
      log('RETRY_START',c);
      await new Promise(w=>setTimeout(w,300+Math.random()*500));
      const d=await okxF('/api/v5/market/candles?instId='+c+'-USDT-SWAP&bar=4H&limit=200');
      if(d&&d.length>50){const dr=d.reverse();
        kd[c]={h:dr.map(k=>+k[2]),l:dr.map(k=>+k[3]),c:dr.map(k=>+k[4]),v:dr.map(k=>+k[5]),t:dr.map(k=>+k[0])};
        fail=fail.filter(x=>x!==c);
        log('RETRY_OK',c+' recovered');}
      else log('RETRY_FAIL',c+' still short bars='+(d?d.length:0));
    }catch(e){log('RETRY_ERR',c+' '+e.message);}}
  }
  const ok=COINS.filter(c=>kd[c]&&kd[c].c).length;
  log('DATA_B_END','success='+ok+'/'+COINS.length+' failed='+fail.length+' total_time='+((Date.now()-st)/1000).toFixed(1)+'秒');
  log('KV_WRITE_START','key=data_b');
  const kvData={status:'ready',ts:Date.now(),d:kd};
  await kvW('data_b',kvData);
  const kvSize=JSON.stringify(kvData).length;
  log('KV_WRITE_OK','timestamp='+new Date(kvData.ts).toISOString()+' size='+kvSize+'bytes');
  log('END','耗时'+(Date.now()-st)+'ms');
  return 'DATA-B '+ok+'/'+COINS.length+' '+(Date.now()-st)+'ms';
}
addEventListener('fetch',e=>e.respondWith(run().then(r=>new Response(r)).catch(er=>new Response('E:'+er.message))));
addEventListener('scheduled',e=>e.waitUntil(run().catch(er=>console.log(er.message))));
