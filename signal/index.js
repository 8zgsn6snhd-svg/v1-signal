// V1-SIGNAL-1.1 — 读KV + 时间戳检查 + /health
const CFG={S1:[6,1.0],S2:[10,2.5],S3:[14,5.0],TP:5,MR:3,VOL_FILTER:0.5,VERSION:'SIGNAL-1.1',
  TOKEN:typeof PUSHPLUS_TOKEN!=='undefined'?PUSHPLUS_TOKEN:'',
  BACKUP:['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK','BCH','LTC','ZEC',
    'SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR','TRX','ONDO','ENA','UNI',
    'HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF']};
const KVID='1074343ba32f4d43be99455ff88cfecb';
const AID='503d56d255b8bfd89e71160f3f98f8df';
const CF_TOK=typeof CF_API_TOKEN!=='undefined'?CF_API_TOKEN:'';
const NAME='SIGNAL';
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
async function kvR(key){
  if(!CF_TOK){log('KV','NO_CF_TOKEN');return null;}
  try{const r=await fetch('https://api.cloudflare.com/client/v4/accounts/'+AID+'/storage/kv/namespaces/'+KVID+'/values/'+key,
    {headers:{'Authorization':'Bearer '+CF_TOK}});
    if(!r.ok){log('KV',key+' HTTP'+r.status);return null;}return await r.json();
  }catch(e){return null;}}

async function run(sch){
  log('START','sch='+sch);
  const n=new Date(),ns=n.toISOString().slice(0,16).replace('T',' ');
  if(sch)try{await pu('['+CFG.VERSION+']',ns);}catch(e){}

  // 读KV + 时间戳检查
  const keys=['data_a','data_b','data_c'];
  const kd={};let tsInfo={},expired=[];
  for(const key of keys){
    const v=await kvR(key);
    if(v&&v.d){
      Object.assign(kd,v.d);
      tsInfo[key]={ts:v.ts,age:Date.now()-v.ts};
      if(Date.now()-v.ts>4.5*3600000)expired.push(key);
    }else{tsInfo[key]={ts:0,age:-1};expired.push(key);}
  }
  const ok=CFG.BACKUP.filter(c=>kd[c]&&kd[c].c).length;
  log('KV','A:'+(tsInfo.data_a.age?Math.round(tsInfo.data_a.age/60000)+'min':'无')+
       ' B:'+(tsInfo.data_b.age?Math.round(tsInfo.data_b.age/60000)+'min':'无')+
       ' C:'+(tsInfo.data_c.age?Math.round(tsInfo.data_c.age/60000)+'min':'无')+
       ' 合计:'+ok+'/34');
  if(expired.length)log('WARN','数据过期:'+expired.join(','));

  let btcDir='';const bk=kd['BTC'];
  if(bk&&bk.c&&bk.c.length){const s3=st(bk.h,bk.l,bk.c,...CFG.S3);if(s3){const d=s3.dr[bk.c.length-2];btcDir=d===1?'S':'L';}}
  const sigs=[],nos=[];
  for(const c of CFG.BACKUP){
    const k=kd[c];if(!k||!k.c||!k.c.length){nos.push({c});continue;}
    const p=k.c[k.c.length-1],s3=st(k.h,k.l,k.c,...CFG.S3),dir=s3?s3.dr[k.c.length-2]:0;
    const a=an(c,k.h,k.l,k.c,k.v,0);let sc=0,hs=0,Rv=0,dst=0,dm=0;
    if(a&&a.cT&&a.R>0.3&&a.R<=3){Rv=a.R;dst=a.sp?Math.abs(a.cu-a.sp)/a.cu*100:99;dm=a.dm;hs=dst<=3;
      if(hs){sc=Math.round(50+Math.min(20,(Rv-0.3)/2.7*20))+Math.max(0,25-Math.abs(dst-1.5)*10)+(dm?15:0);}}
    (hs?sigs:nos).push({c,p,dir,sc,R:Rv,dst,dm});
  }
  sigs.sort((a,b)=>b.sc-a.sc);
  log('STRATEGY','信号:'+sigs.length);
  for(const s of sigs)log('SIGNAL',s.c+' '+(s.dir===1?'S':'L')+' 评分:'+s.sc+' R:'+s.R.toFixed(1));

  const status=ok>=CFG.BACKUP.length-2?'正常':(ok>=CFG.BACKUP.length*0.7?'数据不足':'数据严重不足');
  let r='['+CFG.VERSION+'] '+ns+(btcDir?' BTC:'+btcDir:'')+'\n';
  r+=status+' '+ok+'/'+CFG.BACKUP.length+'\n';
  if(expired.length)r+='⚠️ 数据过期:'+expired.join(',')+'\n';
  if(!sigs.length)r+='无信号\n';
  for(const s of sigs)r+=s.c+' '+(s.dir===1?'S':'L')+' '+s.sc+' R:'+s.R.toFixed(1)+' d:'+s.dst.toFixed(1)+'% $'+pf(s.p)+(s.dm?' OK':'')+'\n';
  if(nos.length){r+='--\n';for(const x of nos)r+=x.c+' '+(x.dir?sd(x.dir):'?')+' '+(x.p?'$'+pf(x.p):'x')+(x.sc?' '+x.sc:'')+'\n';}
  log('PUSH','标题:'+(sigs.length?'V1 '+sigs.map(s=>s.c+(s.dir===1?'S':'L')+'R'+s.R.toFixed(1)).join(' '):'V1 '+status));
  await pu(sigs.length?'V1 '+sigs.map(s=>s.c+(s.dir===1?'S':'L')+'R'+s.R.toFixed(1)).join(' '):'V1 '+status+' '+ok+'/'+CFG.BACKUP.length,r);
  log('END','');
  return r;
}
async function health(e){
  const ka=await kvR('data_a');const kb=await kvR('data_b');const kc=await kvR('data_c');
  const a=ka&&ka.d?Object.keys(ka.d).length:0;
  const b=kb&&kb.d?Object.keys(kb.d).length:0;
  const c=kc&&kc.d?Object.keys(kc.d).length:0;
  const j={status:'ok',data_a:a+'/12',data_b:b+'/12',data_c:c+'/10',okx_key:typeof OKX_API_KEY!=='undefined'?'✅':'❌'};
  return new Response(JSON.stringify(j),{headers:{'Content-Type':'application/json'}});
}
addEventListener('fetch',e=>{const u=new URL(e.request.url);
  if(u.pathname==='/health')return e.respondWith(health(e));
  if(u.pathname==='/testpush'){const ts=new Date().toISOString().slice(0,19).replace('T',' ');
    return e.respondWith(pu('['+CFG.VERSION+'] TEST '+ts,'诊断推送<br>时间:'+ts+'<br>Token:'+(CFG.TOKEN?'已配置':'缺失')).then(r=>new Response('OK code='+r.code)));
  }
  e.respondWith(run(false).then(r=>new Response(r)).catch(er=>new Response('E:'+er.message)));
});
addEventListener('scheduled',e=>{e.waitUntil(run(true).catch(er=>console.log(er.message)));});
