// V1-SIGNAL-1.4 — V1.6 W_btc 信号质量评分门禁 (追加, 策略逻辑不变)
const CFG={S1:[6,1.0],S2:[10,2.5],S3:[14,5.0],TP:5,MR:3,VOL_FILTER:0.5,VERSION:'SIGNAL-1.4',
  TOKEN:typeof PUSHPLUS_TOKEN!=='undefined'?PUSHPLUS_TOKEN:'',
  BACKUP:['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK','BCH','LTC','ZEC',
    'SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR','TRX','ONDO','ENA','UNI',
    'HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF']};
const KVID='1074343ba32f4d43be99455ff88cfecb';
const POOL_KVID='7d4e8decec9849e8becab243a3d4de15';
const AID='503d56d255b8bfd89e71160f3f98f8df';
const CF_TOK=typeof CF_API_TOKEN!=='undefined'?CF_API_TOKEN:'';
const NAME='SIGNAL';
// 固定fallback池 (V1.8冻结34币)
const FIXED_POOL=['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK',
  'BCH','LTC','ZEC','SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR',
  'TRX','ONDO','ENA','UNI','HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF'];
function log(t,m){console.log('['+NAME+']['+t+'] '+m);}

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
// ===== V1.6 W_btc 信号质量评分 (与回测 ScoreFilter 一致, 阈值60) =====
function ema(arr,p){const n=arr.length,out=Array(n).fill(0);
  if(n<p)return out;const k=2/(p+1);let s=0;
  for(let i=0;i<p;i++)s+=arr[i];out[p-1]=s/p;
  for(let i=p;i<n;i++)out[i]=arr[i]*k+out[i-1]*(1-k);
  return out;}
function macd(arr){const e12=ema(arr,12),e26=ema(arr,26);
  return e12.map((v,i)=>v-e26[i]);}
// 5因子: BTC ST1同向+30 / 量>90均量+20 / ST1距离扩大+20 / EMA60同向+20 / MACD同号+10
// dir: 生产方向(1=S空/-1=L多, 即ST dr原值); btcST1: BTC ST1的dr原值
function wbscore(dir,ix,k,s1,btcST1){
  let s=0;
  if(btcST1!==0&&btcST1===dir)s+=30;                    // BTC ST1同向 +30
  const px=k.c[ix],cv=k.v[ix];
  if(ix>=90){let av=0;for(let j=ix-90;j<ix;j++)av+=k.v[j];av/=90;
    if(av>0&&cv>av)s+=20;}                              // 量>90日均量 +20
  if(ix>=7&&s1&&s1.ln){const d0=Math.abs(px-s1.ln[ix])/px*100;
    const d6=Math.abs(k.c[ix-6]-s1.ln[ix-6])/k.c[ix-6]*100;
    if(d0>d6)s+=20;}                                    // ST1距离较6根前扩大 +20
  if(ix>=60){const e60=ema(k.c,60)[ix];
    if(e60>0&&((dir===-1&&px>e60)||(dir===1&&px<e60)))s+=20;} // 价格与EMA60同向 +20
  if(ix>=26){const md=macd(k.c)[ix];
    if((dir===-1&&md>0)||(dir===1&&md<0))s+=10;}        // MACD同号 +10
  return s;}
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
function pf(v){if(v<1e-8)return'0';if(v<1e-4)return v.toFixed(8);if(v<1e-2)return v.toFixed(6);if(v<1)return v.toFixed(4);return v.toFixed(2);}
function sd(d){return d===1?'S':'L';}
async function pu(t,c){
  const tok=CFG.TOKEN;if(!tok){log('PUSH','NO_TOKEN');return{ok:false,err:'no token'};}
  try{const r=await fetch('https://www.pushplus.plus/send',{method:'POST',headers:{'Content-Type':'application/json;charset=utf-8'},
    body:JSON.stringify({token:tok,title:t,content:c.replace(/\n/g,'<br>'),template:'html'})});
    const j=await r.json();const ok=j.code===200;
    log('PUSH',(ok?'OK':'FAIL')+' code='+j.code);
    return{ok,code:j.code,msg:j.msg};
  }catch(e){log('PUSH','ERR '+e.message);return{ok:false,err:e.message};}}
async function kvR(key,kvid){
  if(!CF_TOK){log('KV','NO_CF_TOKEN');return null;}
  const ns=kvid||KVID;
  try{const r=await fetch('https://api.cloudflare.com/client/v4/accounts/'+AID+'/storage/kv/namespaces/'+ns+'/values/'+key,
    {headers:{'Authorization':'Bearer '+CF_TOK}});
    if(!r.ok){log('KV',key+' HTTP'+r.status);return null;}return await r.json();
  }catch(e){return null;}}
async function kvW(key,val){
  if(!CF_TOK){log('KV','NO_CF_TOKEN');return;}
  try{await fetch('https://api.cloudflare.com/client/v4/accounts/'+AID+'/storage/kv/namespaces/'+KVID+'/values/'+key,
    {method:'PUT',headers:{'Authorization':'Bearer '+CF_TOK,'Content-Type':'application/json'},body:JSON.stringify(val)});
  }catch(e){log('KV','PUT_FAIL:'+e.message);}
}
function nextRun(){
  const n=new Date();
  for(let i=1;i<=25;i++){
    const t=new Date(n.getTime()+i*3600000);
    if(t.getUTCHours()%4===0){t.setUTCMinutes(4,0,0);return t.toISOString().slice(11,16);}
  }
  return '?';
}

async function run(sch){
  log('START','sch='+sch);
  const n=new Date(),ns=n.toISOString().slice(0,16).replace('T',' ');

  // 读动态池 (KV pool.coins), 决定扫描币种
  let scanCoins=CFG.BACKUP, poolMode='fixed', poolInfo=null;
  try{
    const pool=await kvR('pool',POOL_KVID);
    if(pool&&pool.coins&&pool.coins.length>=20){
      scanCoins=pool.coins.slice(0,33);
      poolMode=pool.mode||'dynamic';
      poolInfo=pool;
      log('POOL','使用动态池 '+scanCoins.length+'币 mode='+poolMode+' 时间:'+pool.time);
    }else{
      log('POOL','pool不可用, fallback固定池 '+scanCoins.length+'币');
    }
  }catch(e){log('POOL','读取失败 '+e.message+' fallback固定池');}

  // 读 ohlcv_A/B/C + ready检测 (expect为参考, 动态池下每组币数可能不同)
  const groups=[{key:'ohlcv_A',name:'A组',expect:12},{key:'ohlcv_B',name:'B组',expect:12},{key:'ohlcv_C',name:'C组',expect:9}];
  const kd={};const gInfo={};
  for(const g of groups){
    let v=await kvR(g.key);
    for(let w=0;w<5;w++){
      if(v&&v.status==='ready')break;
      log('KV_WAIT',g.key+' status='+(v?v.status:'null')+' 等待1s ('+(w+1)+'/5)');
      await new Promise(r=>setTimeout(r,1000));
      v=await kvR(g.key);
    }
    let ok=0,failed=[],ageS=-1;
    if(v&&v.status==='ready'&&v.data){
      const dd=v.data;ok=Object.keys(dd).length;failed=v.failed||[];
      ageS=Math.round((Date.now()-v.ts)/1000);
      Object.assign(kd,dd);
    }
    gInfo[g.key]={v,ok,failed,ageS,expect:g.expect};
    log('KV_READ',g.name+' '+g.key+': exists='+(v&&v.status==='ready')+' success='+ok+'/'+g.expect+' failed='+(failed.length?failed.join(','):'无')+' age='+ageS+'秒');
  }
  const ok=scanCoins.filter(c=>kd[c]&&kd[c].c).length;
  const missing=scanCoins.filter(c=>!kd[c]||!kd[c].c);
  log('MERGE','total='+ok+'/'+scanCoins.length+' pool='+poolMode);

  // 数据报告
  log('REPORT','========== V1 DATA REPORT ==========');
  for(const g of groups){
    const gi=gInfo[g.key];
    const okc=gi.ok||0;
    log('REPORT',g.name+':');
    log('REPORT','  成功: '+okc+'/'+gi.expect);
    log('REPORT','  失败: '+(gi.failed&&gi.failed.length?gi.failed.join(','):'无'));
  }
  log('REPORT','最终:');
  log('REPORT','  '+scanCoins.length+'币('+poolMode+') 成功: '+ok+' 失败: '+(missing.length?missing.join(','):'0'));
  log('REPORT','====================================');

  // 保存运行状态到KV (供 /status)
  const statusRec={last_run:ns,data:ok,pool:poolMode,failed:missing.slice(0,20),ts:Date.now()};
  await kvW('signal_status',statusRec);

  // 完整检查: 动态池 <30/33 自动fallback固定池
  let usePool=scanCoins;
  if(poolMode==='dynamic'&&ok<30){
    log('FALLBACK','动态池数据不足 '+ok+'/'+scanCoins.length+' (<30), fallback固定池');
    usePool=FIXED_POOL;
    const okF=usePool.filter(c=>kd[c]&&kd[c].c).length;
    log('FALLBACK','固定池数据 '+okF+'/'+usePool.length);
    poolMode='fixed-fallback';
  }

  // 合并阈值: <30 禁止发送交易信号
  if(ok<30){
    log('DIAG','数据严重不足 '+ok+'/'+scanCoins.length+' 禁止发信号');
    let r='⚠️ 数据不足\n成功: '+ok+'/'+scanCoins.length+' ('+poolMode+')\n失败币: '+(missing.length?missing.join(','):'无')+'\n';
    r+='下次: '+nextRun()+'\n';
    await pu('⚠️ V1 数据不足 '+ok+'/'+scanCoins.length+' ('+poolMode+')',r);
    log('END','');
    return r;
  }

  // ===== 以下为 V1 策略逻辑(冻结,不改) =====
  let btcDir='',btcST1=0;const bk=kd['BTC'];
  if(bk&&bk.c&&bk.c.length){const s3=st(bk.h,bk.l,bk.c,...CFG.S3);if(s3){const d=s3.dr[bk.c.length-2];btcDir=d===1?'S':'L';}
    const s1b=st(bk.h,bk.l,bk.c,...CFG.S1);if(s1b)btcST1=s1b.dr[bk.c.length-2];} // V1.6 W_btc: BTC ST1方向(仅评分用)
  const sigs=[],nos=[];
  for(const c of usePool){
    const k=kd[c];if(!k||!k.c||!k.c.length){nos.push({c});continue;}
    const p=k.c[k.c.length-1],s3=st(k.h,k.l,k.c,...CFG.S3),s1=st(k.h,k.l,k.c,...CFG.S1),
          dir=s3?s3.dr[k.c.length-2]:0;
    const a=an(c,k.h,k.l,k.c,k.v,0);let sc=0,hs=0,Rv=0,dst=0,dm=0,wbtc=0;
    if(a&&a.cT&&a.R>0.3&&a.R<=3){Rv=a.R;dst=a.sp?Math.abs(a.cu-a.sp)/a.cu*100:99;dm=a.dm;hs=dst<=3;
      if(hs){wbtc=wbscore(dir,a.ix,k,s1,btcST1);        // V1.6 W_btc 评分门禁
        if(wbtc>=60){sc=Math.round(50+Math.min(20,(Rv-0.3)/2.7*20))+Math.max(0,25-Math.abs(dst-1.5)*10)+(dm?15:0);}
        else{hs=false;}}}                                // score<60 过滤
    (hs?sigs:nos).push({c,p,dir,sc,R:Rv,dst,dm,wbtc});
  }
  sigs.sort((a,b)=>b.sc-a.sc);
  log('STRATEGY','信号:'+sigs.length+' pool='+poolMode);
  for(const s of sigs)log('SIGNAL',s.c+' '+(s.dir===1?'S':'L')+' 评分:'+s.sc+' wbtc:'+s.wbtc+' R:'+s.R.toFixed(1));

  const status=ok>=scanCoins.length-2?'正常':(ok>=scanCoins.length*0.7?'数据不足':'数据严重不足');
  let r='['+CFG.VERSION+'] '+ns+(btcDir?' BTC:'+btcDir:'')+' ('+poolMode+')\n';
  r+=status+' '+ok+'/'+scanCoins.length+'\n';
  if(missing.length)r+='⚠️ 缺失:'+missing.join(',')+'\n';
  if(!sigs.length)r+='无信号\n';
  for(const s of sigs)r+=s.c+' '+(s.dir===1?'S':'L')+' '+s.sc+' R:'+s.R.toFixed(1)+' d:'+s.dst.toFixed(1)+'% $'+pf(s.p)+' w:'+s.wbtc+(s.dm?' OK':'')+'\n';
  if(nos.length){r+='--\n';for(const x of nos)r+=x.c+' '+(x.dir?sd(x.dir):'?')+' '+(x.p?'$'+pf(x.p):'x')+(x.sc?' '+x.sc:'')+(x.wbtc?' w:'+x.wbtc:'')+'\n';}
  log('PUSH','标题:'+(sigs.length?'V1 '+sigs.map(s=>s.c+(s.dir===1?'S':'L')+'R'+s.R.toFixed(1)).join(' '):'V1 '+status));
  await pu(sigs.length?'V1 '+sigs.map(s=>s.c+(s.dir===1?'S':'L')+'R'+s.R.toFixed(1)).join(' '):'V1 '+status+' '+ok+'/'+scanCoins.length+' ('+poolMode+')',r);
  log('END','');
  return r;
}
async function health(e){
  const ka=await kvR('ohlcv_A');const kb=await kvR('ohlcv_B');const kc=await kvR('ohlcv_C');
  const a=ka&&ka.data?Object.keys(ka.data).length:0;
  const b=kb&&kb.data?Object.keys(kb.data).length:0;
  const c=kc&&kc.data?Object.keys(kc.data).length:0;
  const j={status:'ok',data_a:a+'/12',data_b:b+'/12',data_c:c+'/10',okx_key:typeof OKX_API_KEY!=='undefined'?'✅':'❌'};
  return new Response(JSON.stringify(j),{headers:{'Content-Type':'application/json'}});
}
async function status(e){
  const s=await kvR('signal_status');
  const ka=await kvR('ohlcv_A');const kb=await kvR('ohlcv_B');const kc=await kvR('ohlcv_C');
  const age=(v)=>v?Math.round((Date.now()-v.ts)/1000)+'s':'-';
  const j={
    status:'ok',version:CFG.VERSION,
    last_run:s?s.last_run:null,
    data:(s?s.data:0)+'/33',
    pool:(s&&s.pool)?s.pool:'?',
    recent_failed:(s&&s.failed&&s.failed.length)?s.failed:'无',
    next_run:nextRun(),
    data_a:ka?{success:Object.keys(ka.data||{}).length,failed:ka.failed||[],age:age(ka)}:null,
    data_b:kb?{success:Object.keys(kb.data||{}).length,failed:kb.failed||[],age:age(kb)}:null,
    data_c:kc?{success:Object.keys(kc.data||{}).length,failed:kc.failed||[],age:age(kc)}:null
  };
  return new Response(JSON.stringify(j),{headers:{'Content-Type':'application/json'}});
}
async function testDebug(e){
  const ka=await kvR('ohlcv_A');const kb=await kvR('ohlcv_B');const kc=await kvR('ohlcv_C');
  const a=ka&&ka.data?Object.keys(ka.data).length:0;
  const b=kb&&kb.data?Object.keys(kb.data).length:0;
  const c=kc&&kc.data?Object.keys(kc.data).length:0;
  const j={
    data_a:{success:a,failed:12-a,age:ka?Math.round((Date.now()-ka.ts)/1000)+'s':'-',failedList:ka?ka.failed:[]},
    data_b:{success:b,failed:12-b,age:kb?Math.round((Date.now()-kb.ts)/1000)+'s':'-',failedList:kb?kb.failed:[]},
    data_c:{success:c,failed:10-c,age:kc?Math.round((Date.now()-kc.ts)/1000)+'s':'-',failedList:kc?kc.failed:[]},
    merge:{total:a+b+c,expected:34},
    kv_token:CF_TOK?'✅':'❌',
    push_token:CFG.TOKEN?'✅':'❌',
    version:CFG.VERSION
  };
  return new Response(JSON.stringify(j),{headers:{'Content-Type':'application/json'}});
}
addEventListener('fetch',e=>{const u=new URL(e.request.url);
  if(u.pathname==='/health')return e.respondWith(health(e));
  if(u.pathname==='/status')return e.respondWith(status(e));
  if(u.pathname==='/testdebug')return e.respondWith(testDebug(e));
  if(u.pathname==='/testpush'){const ts=new Date().toISOString().slice(0,19).replace('T',' ');
    return e.respondWith(pu('['+CFG.VERSION+'] TEST '+ts,'诊断推送<br>时间:'+ts+'<br>Token:'+(CFG.TOKEN?'已配置':'缺失')).then(r=>new Response('OK code='+r.code)));
  }
  e.respondWith(run(false).then(r=>new Response(r)).catch(er=>new Response('E:'+er.message)));
});
addEventListener('scheduled',e=>{e.waitUntil(run(true).catch(er=>console.log(er.message)));});
