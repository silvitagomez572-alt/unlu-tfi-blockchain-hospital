// Isolated frontend error-state tests. No browser, server or infrastructure.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const started=performance.now(),elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'',className:'',value:'',addEventListener(){},classList:{add(){},toggle(){}}});return elements.get(id);};
const context=vm.createContext({document:{getElementById:element,querySelector:()=>({content:'test-csrf-not-a-credential'}),querySelectorAll:()=>[]},location:{origin:'http://127.0.0.1:19980'},AbortController,setTimeout,clearTimeout,fetch:async()=>{throw new TypeError('Failed to fetch');}});
const source=fs.readFileSync(path.join(__dirname,'../../webconsole/static/app.js'),'utf8');
assert.ok(source.trimEnd().endsWith('boot();'));
vm.runInContext(source.trimEnd().slice(0,-7),context,{timeout:1000});
const run=code=>vm.runInContext(code,context,{timeout:1000});
async function main(){
  const cases=[];
  await assert.rejects(run("api('summary')"),/servidor local/);cases.push('network read is explained');
  assert.equal(element('api-status').textContent,'No comprobada');
  assert.equal(element('stat-height').textContent,'—');
  assert.equal(element('validation-pill').textContent,'Datos desactualizados');cases.push('stale live indicators cleared');
  await assert.rejects(run("api('command', {action:'mine'})"),/No se conoce el resultado del envío/);cases.push('unknown write is not retried');
  context.fetch=async()=>({ok:false,status:403,json:async()=>({detail:'local session required; reload console'})});
  await assert.rejects(run("api('summary')"),/Recargá esta página/);cases.push('expired session distinct');
  context.fetch=async()=>({ok:false,status:403,json:async()=>({detail:'origin denied'})});
  await assert.rejects(run("api('summary')"),/origen o permisos/);cases.push('security refusal retained');
  context.fetch=async()=>({ok:false,status:422,json:async()=>({detail:'invalid request schema'})});
  await assert.rejects(run("api('command', {})"),/invalid request schema/);cases.push('schema error retained');
  let options;
  context.fetch=async(url,opts)=>{assert.equal(url,'/console/api/summary');options=opts;return{ok:true,status:200,json:async()=>({height:2})};};
  assert.equal((await run("api('summary')")).height,2);
  assert.equal(options.credentials,'same-origin');assert.equal(options.headers['X-HISJB-CSRF'],'test-csrf-not-a-credential');cases.push('same origin and CSRF retained');
  context.fetch=async()=>({ok:true,status:204});assert.equal(await run("api('command', {})"),null);cases.push('204 supported');
  element('verify-result').textContent='Old MATCH';run('unverified()');assert.match(element('verify-result').textContent,/no verificada/);cases.push('prior integrity result cleared');
  console.log(JSON.stringify({status:'PASS',scope:'frontend error handling only; mocked fetch; not an Edge demonstration',cases,elapsed_ms:performance.now()-started,rss_bytes:process.memoryUsage().rss},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
