// V1-SIGNAL-1.0 — 4h C信号扫描器
// 读取V1_POOL币池 → 200根4H → V1计算 → 推送
const CFG={S1:[6,1.0],S2:[10,2.5],S3:[14,5.0],TP:5,MR:3,VOL_FILTER:0.5,TOKEN:'TOKEN',VERSION:'SIGNAL-1.0',BACKUP:['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK','BCH','LTC','ZEC','SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR','TRX','ONDO','ENA','UNI','HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF']};
function st(h,l,c,p,m){if(!c||c.length<p)return null;const n=c.length,hl=Array(n);for(let i=0;i<n;i++)hl[i]=(h[i]+l[i])/2;const tr=Array(n).fill(0);for(let i=1;i<n;i++)tr[i]=Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1]));const at=Array(n).fill(0);let s=0;for(let i=0;i<p;i++)s+=tr[i];at[p-1]=s/p;for(let i=p;i<n;i++)at[i]=(at[i-1]*(p-1)+tr[i])/p;const up=Array(n),lo=Array(n),ln=Array(n),dr=Array(n);up[p-1]=hl[p-1]+m*at[p-1];lo[p-1]=hl[p-1]-m*at[p-1];dr[p-1]=1;ln[p-1]=up[p-1];for(let i=p;i<n;i++){const u=hl[i]+m*at[i],lw=hl[i]-m*at[i];up[i]=(u<up[i-1]||c[i-1]>up[i-1])?u:up[i-1];lo[i]=(lw>lo[i-1]||c[i-1]<lo[i-1])?lw:lo[i-1];const x=Math.abs(ln[i-1]-up[i-1])<Math.abs(ln[i-1]-lo[i-1]);dr[i]=x?(c[i]>up[i]?-1:1):(c[i]<lo[i]?1:-1);ln[i]=dr[i]===-1?lo[i]:up[i];}return{ln,dr};}
function an(cn,h,l,c,vl,bd){const cu=c[c.length-1],ix=c.length-2;const s1=st(h,l,c,...CFG.S1),s2=st(h,l,c,...CFG.S2),s3=st(h,l,c,...CFG.S3);if(!s1||!s2||!s3||ix<1)return null;const cv=vl[ix];const lb=Math.min(90,ix-1);let av=0;for(let j=ix-lb;j<ix;j++)av+=vl[j];av/=lb;if(av>0&&cv<av*CFG.VOL_FILTER)return null;const d1=s1.dr[ix],d2=s2.dr[ix],d3=s3.dr[ix];const cT=(d1===d2&&d2===d3)&&!(s1.dr[ix-1]===s2.dr[ix-1]&&s2.dr[ix-1]===s3.dr[ix-1]);const sh=d1===1;let R=0,sp=0;if(cT){sp=s1.ln[ix];R=sh?((sp/cu-1)*100):((cu/sp-1)*100);}return{cu,ix,cT,R,sh,sp,dm:bd===d1};}
function pf(v){if(v<1e-8)return'0';if(v<1e-4)return v.toFixed(8);if(v<1e-2)return v.toFixed(6);if(v<1)return v.toFixed(4);return v.toFixed(2);}
function sd(d){return d===1?'S':'L';}
async function gk(c,inst){
  const a=new AbortController(),t=setTimeout(()=>a.abort(),12000);inst=inst||c+'-USDT';
  try{
    const r=await fetch('https://www.okx.com/api/v5/market/candles?instId='+inst+'&bar=4H&limit=100',{headers:{'User-Agent':'CF'},signal:a.signal});
    if(!r.ok)throw Error('H'+r.status);const j=await r.json();
    if(j.code!=='0')throw Error('C'+j.code);if(!j.data||j.data.length<50)throw Error('s');
    const d=j.data.reverse();
    return{h:d.map(k=>+k[2]),l:d.map(k=>+k[3]),c:d.map(k=>+k[4]),v:d.map(k=>+k[5]),t:d.map(k=>+k[0])};
  }finally{clearTimeout(t);}
}
async function pu(t,c){try{const r=await fetch('https://www.pushplus.plus/send',{method:'POST',headers:{'Content-Type':'application/json;charset=utf-8'},body:JSON.stringify({token:CFG.TOKEN,title:t,content:c.replace(/\n/g,'<br>'),template:'html'})});const j=await r.json();return{ok:j.code===200,code:j.code,msg:j.msg};}catch(e){return{ok:false,err:e.message};}}

async function run(sch){
  const exeId=Date.now().toString(36);
  const n=new Date(),ns=n.toISOString().slice(0,16).replace('T',' ');
  if(sch){try{await pu('['+CFG.VERSION+'] 运行 '+ns.slice(11,16),'sch='+sch);}catch(e){}}
  await new Promise(w=>setTimeout(w,500+Math.random()*1000));

  // 读取币池
  let coins=CFG.BACKUP,insts=CFG.BACKUP.map(c=>c+'-USDT-SWAP');
  const PKV=typeof V1_POOL!=='undefined'?V1_POOL:null;
  if(PKV){
    try{const p=await PKV.get('pool');if(p){const pp=JSON.parse(p);if(pp.coins&&pp.coins.length>10){coins=pp.coins;insts=pp.insts||pp.coins.map(c=>c+'-USDT-SWAP');}}}catch(e){}
  }

  // 数据获取
  const kd={};const tf=coins.map((c,i)=>({c,inst:insts[i]||c+'-USDT'}));
  for(let i=0;i<tf.length;i+=2){
    const b=tf.slice(i,i+2);const rr=await Promise.allSettled(b.map(x=>gk(x.c,x.inst)));
    rr.forEach((r,j)=>{if(r.status==='fulfilled'&&r.value)kd[b[j].c]=r.value;});
    if(i+2<tf.length)await new Promise(w=>setTimeout(w,1200));
  }
  for(let r=0;r<2;r++){
    const fl=tf.filter(x=>!kd[x.c]);if(!fl.length)break;
    await new Promise(w=>setTimeout(w,1000));
    for(const f of fl.slice(0,8)){try{kd[f.c]=await gk(f.c,f.inst);}catch(e){}}
  }
  const okCount=coins.filter(c=>kd[c]&&kd[c].c).length;
  const failCoins=coins.filter(c=>!kd[c]||!kd[c].c);

  // BTC可选
  let btcDir='';
  const bk=kd['BTC'];
  if(bk&&bk.c&&bk.c.length){const s3=st(bk.h,bk.l,bk.c,...CFG.S3);if(s3){const d=s3.dr[bk.c.length-2];btcDir=d===1?'S':'L';}}

  // 策略
  const sigs=[],nos=[];
  for(const c of coins){
    const k=kd[c];if(!k||!k.c||!k.c.length){nos.push({c});continue;}
    const p=k.c[k.c.length-1],s3=st(k.h,k.l,k.c,...CFG.S3),dir=s3?s3.dr[k.c.length-2]:0;
    const a=an(c,k.h,k.l,k.c,k.v,0);let sc=0,hs=0,Rv=0,dst=0,dm=0;
    if(a&&a.cT&&a.R>0.3&&a.R<=3){Rv=a.R;dst=a.sp?Math.abs(a.cu-a.sp)/a.cu*100:99;dm=a.dm;hs=dst<=3;if(hs){sc=Math.round(50+Math.min(20,Math.max(0,(Rv-0.3)/2.7*20))+Math.max(0,25-Math.abs(dst-1.5)*10)+(dm?15:0));}}
    (hs?sigs:nos).push({c,p,dir,sc,R:Rv,dst,dm});
  }
  sigs.sort((a,b)=>b.sc-a.sc);

  // 状态+报告
  const status=okCount>=coins.length-2?'正常':(okCount>=coins.length*0.7?'数据不足':'数据严重不足');
  let r='['+CFG.VERSION+'] '+ns+(btcDir?' BTC:'+btcDir:'')+'\n';
  r+=status+' '+okCount+'/'+coins.length+'\n';
  if(!sigs.length)r+='无信号\n';
  for(const s of sigs)r+=s.c+' '+(s.dir===1?'S':'L')+' '+s.sc+' R:'+s.R.toFixed(1)+' d:'+s.dst.toFixed(1)+'% $'+pf(s.p)+(s.dm?' OK':'')+'\n';
  if(nos.length){r+='--\n';for(const x of nos)r+=x.c+' '+(x.dir?sd(x.dir):'?')+' '+(x.p?'$'+pf(x.p):'x')+(x.sc?' '+x.sc:'')+'\n';}

  const sub=sigs.length?'V1 '+sigs.map(s=>s.c+(s.dir===1?'S':'L')+'R'+s.R.toFixed(1)).join(' '):'V1 '+status+' '+okCount+'/'+coins.length;
  await pu(sub,r);
  return r;
}
async function testPush(e){
  const n=new Date(),ts=n.toISOString().slice(0,19).replace('T',' ');
  const title='['+CFG.VERSION+'] TEST '+ts;
  const content='['+CFG.VERSION+'] 诊断推送<br>时间:'+ts;
  const r=await fetch('https://www.pushplus.plus/send',{method:'POST',headers:{'Content-Type':'application/json;charset=utf-8'},body:JSON.stringify({token:CFG.TOKEN,title:title,content:content,template:'html'})});
  const j=await r.json();
  return new Response('testpush v'+CFG.VERSION+' http='+r.status+' code='+j.code+'\n'+JSON.stringify(j));
}
async function testCron(e){return run(true).then(r=>new Response(r)).catch(er=>new Response('E:'+er.message,{status:500}));}
addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.pathname==='/testpush')return e.respondWith(testPush(e));if(u.pathname==='/testcron')return e.respondWith(testCron(e));e.respondWith(run(false).then(r=>new Response(r)).catch(er=>new Response('E:'+er.message,{status:500})));});
addEventListener('scheduled',e=>{e.waitUntil(run(true).catch(er=>console.log(er.message)));});
