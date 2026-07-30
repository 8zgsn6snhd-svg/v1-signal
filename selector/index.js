// V1-SELECTOR-1.0 — 每天 02:00 UTC
// 写入已知稳定的34币池到V1_POOL
const VERSION='SELECTOR-1.0';
const BACKUP=['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK',
  'BCH','LTC','ZEC','SUI','TAO','XLM','NEAR','WLD','INJ','FIL','HBAR',
  'TRX','ONDO','ENA','UNI','HYPE','DOT','APT','ARB','OP','ATOM','NEIRO','GALA','PEPE','WIF'];

async function run(){
  const insts=BACKUP.map(c=>c+'-USDT-SWAP');
  const data={ts:Date.now(),version:VERSION,coins:BACKUP,insts};
  if(typeof V1_POOL!=='undefined'){
    await V1_POOL.put('pool',JSON.stringify(data));
  }
  let r='['+VERSION+'] 选币 '+BACKUP.length+'/34 OK\n';
  for(let i=0;i<BACKUP.length;i++)r+=BACKUP[i]+' '+insts[i]+'\n';
  return r;
}
async function show(){
  let r='['+VERSION+']\n';
  if(typeof V1_POOL!=='undefined'){
    try{const p=await V1_POOL.get('pool');if(p){const pp=JSON.parse(p);r+='池:'+pp.coins.length+'币 更新:'+new Date(pp.ts).toISOString().slice(0,10)+'\n';for(const c of pp.coins)r+=c+'\n';return r;}}catch(e){}
  }
  r+='无池 /cron触发';
  return r;
}
addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(u.pathname==='/cron')return e.respondWith(run().then(r=>new Response(r)));
  e.respondWith(show().then(r=>new Response(r)));
});
addEventListener('scheduled',e=>e.waitUntil(run().catch(er=>console.log(er.message))));
