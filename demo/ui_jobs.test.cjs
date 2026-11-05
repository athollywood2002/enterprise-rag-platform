// Deterministic out-of-order responses against the shipped UI, without a network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.value=''; this.handlers={}; }
  addEventListener(k,f) { this.handlers[k]=f; }
  replaceChildren(...children) { this.children=children; }
  append(...children) { this.children=[...(this.children||[]),...children]; }
  scrollIntoView() {}
}
function fixture() {
  const elements=new Map(), calls=[]; let poll;
  const $=id=>{if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id);};
  const context=vm.createContext({document:{getElementById:$,createElement:()=>new Element()},setInterval:f=>{poll=f;},fetch:(url,options)=>new Promise(resolve=>calls.push({url,options,reply:body=>resolve({ok:true,json:async()=>body}),fail:()=>resolve({ok:false,status:503,json:async()=>({detail:'offline'})})}))});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../src/rag/web/app.js'),'utf8'),context);
  vm.runInContext("key='fixture'; config={};",context);
  return {$,calls,poll:()=>poll(),select:id=>{$('job-select').value=id; return $('job-select').onchange();},load:()=>vm.runInContext('loadJob()',context),mode:value=>vm.runInContext('config.model_mode='+JSON.stringify(value),context)};
}
const job=(id,source=id)=>({id,source,mode:'server',status:'queued',created:1,files:[{path:'a.txt',status:'pending'}],counts:{pending:1,failed:1}});
async function selected(f,id) {const done=f.select(id); f.calls.at(-1).reply(job(id)); await done;}
function displayed(f,id) {assert.match(f.$('job-title').textContent,new RegExp('^'+id+' ·')); assert.equal(f.$('job-select').value,id); assert.equal(f.$('job-panel').hidden,false);}
test('rapid selection rejects a late A status and blocks actions while B loads',async()=>{
 const f=fixture(),a=f.select('A'),ra=f.calls.at(-1),b=f.select('B'),rb=f.calls.at(-1);
 assert.equal(f.$('job-panel').hidden,true); await f.$('cancel').onclick(); assert.equal(f.calls.length,2);
 rb.reply(job('B'));await b; ra.reply(job('A'));await a;displayed(f,'B');
});
test('poll for A cannot repaint B or redirect cancellation',async()=>{
 const f=fixture();await selected(f,'A');const polling=f.poll(),ra=f.calls.at(-1);
 await selected(f,'B');ra.reply(job('A'));await new Promise(setImmediate);
 f.calls.at(-1).reply({documents:[]});await polling;displayed(f,'B');
 const cancel=f.$('cancel').onclick();assert.equal(f.calls.at(-1).url,'/library/jobs/B/cancel');
 f.calls.at(-1).reply(job('B'));await new Promise(setImmediate);f.calls.at(-1).reply(job('B'));await cancel;
});
test('A to B to A rejects the first A response',async()=>{
 const f=fixture(),a=f.select('A'),ra=f.calls.at(-1);await selected(f,'B');await selected(f,'A');
 ra.reply(job('A','obsolete'));await a;displayed(f,'A');
});
test('overlapping requests for the same job retain the newest result',async()=>{
 const f=fixture();await selected(f,'A');const first=f.load(),r=f.calls.at(-1),last=f.load();
 f.calls.at(-1).reply(job('A','newest'));await last;r.reply(job('A','obsolete'));await first;
 assert.match(f.$('job-title').textContent,/^newest/);
});
test('current status failure hides stale progress and disables mutations',async()=>{
 const f=fixture();await selected(f,'A');const load=f.load();f.calls.at(-1).fail();await load;
 assert.equal(f.$('job-panel').hidden,true);assert.equal(f.$('cancel').disabled,true);assert.equal(f.$('retry').disabled,true);
});
test('stale error and cancel response do not repaint a newly selected job',async()=>{
 const f=fixture();await selected(f,'A');const old=f.load(),ra=f.calls.at(-1),cancel=f.$('cancel').onclick(),rc=f.calls.at(-1);
 await selected(f,'B');ra.fail();await old;rc.reply(job('A'));await new Promise(setImmediate);
 assert.equal(f.calls.at(-1).url,'/library/jobs/B');f.calls.at(-1).reply(job('B'));await cancel;displayed(f,'B');
});
test('late job-list refresh cannot reset a user selection',async()=>{
 const f=fixture();await selected(f,'A');const refresh=f.$('refresh-jobs').onclick(),list=f.calls.at(-1);
 await selected(f,'B');list.reply([job('A')]);await refresh;displayed(f,'B');
});
test('retry stays bound to the displayed job when selection changes',async()=>{
 const f=fixture();await selected(f,'A');const retry=f.$('retry').onclick(),request=f.calls.at(-1);
 assert.equal(request.url,'/library/jobs/A/retry');await selected(f,'B');
 request.reply(job('A'));await new Promise(setImmediate);f.calls.at(-1).reply(job('B'));await retry;displayed(f,'B');
});
test('late readiness snapshots cannot overwrite a newer check',async()=>{
 const f=fixture(),first=f.$('refresh-readiness').onclick(),old=f.calls.at(-1),last=f.$('refresh-readiness').onclick();
 const state=mode=>({mode,chat_model:{name:'chat',status:'available'},embedding_model:{name:'embed',status:'available'},checked_at:new Date().toISOString(),metadata_ready:true,ollama:'reachable',qdrant:'reachable'});
 f.calls.at(-1).reply(state('synthetic'));await last;old.reply(state('real'));await first;
  assert.match(f.$('model-mode').textContent,/synthetic/);
});

const metadata=mode=>({mode,chat_model:{name:'chat',status:'available'},embedding_model:{name:'embed',status:'available'},checked_at:new Date().toISOString(),metadata_ready:true,ollama:'reachable',qdrant:'reachable'});
const answer=mode=>({model_mode:mode,answer:'Fixture [1].',sources:[{source:'fixture.txt',text:'Fixture.',chunk:0}],generation:{status:'complete',eval_count:4}});
async function ask(f) {f.$('question').value='Fixture?';f.$('search-scope').value='all';return f.$('ask-form').onsubmit({preventDefault(){}});}
for(const [cached,actual] of [['real','synthetic'],['synthetic','real']]) {
  test(`answer mode comes from response, not cached ${cached} or readiness`,async()=>{
    const f=fixture();f.mode(cached);
    const ready=f.$('refresh-readiness').onclick();f.calls.at(-1).reply(metadata(actual));await ready;
    const asking=ask(f);f.calls.at(-1).reply(answer(actual));await asking;
    assert.match(f.$('generation').textContent,new RegExp('Model mode: '+actual+' '));
    assert.equal(f.$('generation').textContent.includes('simulated reply'),actual==='synthetic');
    assert.match(f.$('generation').textContent,/operator configuration, not evidence of inference/);
  });
  test(`in-flight ${cached} answer keeps its label after readiness changes to ${actual}`,async()=>{
    const f=fixture();f.mode(cached);
    const asking=ask(f),request=f.calls.at(-1);
    const ready=f.$('refresh-readiness').onclick();f.calls.at(-1).reply(metadata(actual));await ready;
    request.reply(answer(cached));await asking;
    assert.match(f.$('model-mode').textContent,new RegExp(actual));
    assert.match(f.$('generation').textContent,new RegExp('Model mode: '+cached+' '));
    assert.equal(f.$('generation').textContent.includes('simulated reply'),cached==='synthetic');
  });
}
for(const mode of [undefined,'unknown','invalid']) {
  test(`missing or unsupported response mode (${mode}) remains unknown`,async()=>{
    const f=fixture();f.mode('real');
    const ready=f.$('refresh-readiness').onclick();f.calls.at(-1).reply(metadata('synthetic'));await ready;
    const asking=ask(f);f.calls.at(-1).reply(answer(mode));await asking;
    assert.match(f.$('generation').textContent,/Model mode: unknown /);
    assert.doesNotMatch(f.$('generation').textContent,/simulated reply/);
  });
}
