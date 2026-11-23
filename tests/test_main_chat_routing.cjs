// Actual adapter functions under Node VM. No browser, server, model or mail requests.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const copy = value => JSON.parse(JSON.stringify(value));
function fn(name) {
  const start = source.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, name);
  const firstLine=source.slice(start,source.indexOf('\n',start));
  if (firstLine.trimEnd().endsWith('}')) return firstLine;
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function assignment(startText) {
  const start = source.indexOf(startText);
  assert.ok(start >= 0, startText);
  return source.slice(start, source.indexOf('\n};', start) + 3);
}
const valid = source.match(/^const AI365_VALID_AGENTS = .*;$/m)[0];
function fixture(extra = {}) {
  const selection = { agents: ['work', 'groupware'], files: ['work:email', 'gw:agent'],
    scope: {knowledge_files: ['policy.pdf'], data_tables: [], data_bi: [], work: true} };
  const ctx = { window: { AI365_SMF_HOOKS: {agents: () => selection.agents, files: () => selection.files,
    scope: () => selection.scope}, AI365_COMPOSER_AGENTS: () => ['work'] },
    ai365CurrentScope: () => '사내', ai365ChatRetry:false, ...extra };
  vm.createContext(ctx);
  vm.runInContext(valid + '\n' + fn('ai365SelectedAgents') + '\n' + fn('ai365SelectionSnapshot'), ctx);
  return {ctx, selection};
}

test('shared selection preserves groupware and explicit workers, independently of legacy filtered hook', () => {
  const {ctx, selection} = fixture();
  assert.deepEqual(copy(vm.runInContext('ai365SelectedAgents()', ctx)), ['work', 'groupware']);
  const snapshot = copy(vm.runInContext('ai365SelectionSnapshot()', ctx));
  assert.deepEqual(snapshot.agents, ['work', 'groupware']);
  assert.deepEqual(snapshot.scopeFiles.workers, ['email']);
  selection.files.push('work:edu');
  assert.deepEqual(copy(vm.runInContext('ai365SelectionSnapshot().scopeFiles.workers', ctx)), ['email', 'edu']);
  assert.deepEqual(snapshot.scopeFiles.workers, ['email']);
});

test('snapshot copies resource arrays before composer changes; explicit opts win', () => {
  const {ctx, selection} = fixture();
  vm.runInContext('saved = ai365SelectionSnapshot()', ctx);
  selection.agents.splice(0, 2, 'data');
  selection.scope.knowledge_files.push('other.pdf');
  selection.files.splice(0, 2, 'work:edu');
  const saved = copy(ctx.saved);
  assert.deepEqual(saved.agents, ['work', 'groupware']);
  assert.deepEqual(saved.scopeFiles.knowledge_files, ['policy.pdf']);
  assert.deepEqual(saved.scopeFiles.workers, ['email']);
  const explicit = copy(vm.runInContext("ai365SelectionSnapshot({agents:['groupware'], scopeFiles:{work:false}})", ctx));
  assert.deepEqual(explicit.agents, ['groupware']);
  assert.equal('workers' in explicit.scopeFiles, false);
});

test('explicit empty or malformed workers stay empty instead of becoming unrestricted', () => {
  const {ctx}=fixture();
  for (const workers of [[], ['unknown'], 'email', null, {}]) {
    ctx.input={scopeFiles:{workers}};
    const scope=copy(vm.runInContext('ai365SelectionSnapshot(input).scopeFiles',ctx));
    assert.deepEqual(scope.workers,[]);
    assert.equal(Object.hasOwn(scope,'workers'),true);
  }
  ctx.input={scopeFiles:{workers:['email'],knowledge_files:['a.pdf'],data_tables:['sales']}};
  vm.runInContext('saved=ai365SelectionSnapshot(input)',ctx);
  ctx.input.scopeFiles.workers.push('edu');
  ctx.input.scopeFiles.knowledge_files.push('b.pdf');
  assert.deepEqual(copy(ctx.saved.scopeFiles.workers),['email']);
  assert.deepEqual(copy(ctx.saved.scopeFiles.knowledge_files),['a.pdf']);
});

test('no worker selection stays unrestricted; automatic/external scope does not inherit internal checks', () => {
  const {ctx, selection} = fixture();
  assert.deepEqual(copy(vm.runInContext("ai365SelectionSnapshot({scope:'자동'}).agents", ctx)), []);
  selection.files = ['gw:agent'];
  assert.equal('workers' in copy(vm.runInContext('ai365SelectionSnapshot().scopeFiles', ctx)), false);
  for (const scope of ['자동', '외부']) {
    ctx.ai365CurrentScope = () => scope;
    const snapshot = copy(vm.runInContext('ai365SelectionSnapshot()', ctx));
    assert.deepEqual(snapshot.agents, []);
    assert.equal('workers' in snapshot.scopeFiles, false);
    assert.deepEqual(snapshot.scopeFiles.knowledge_files, []);
  }
});

test('automation launcher starts one shared chat and carries the combined selection', () => {
  const started = [];
  const input = {value: '고객 인보이스를 취합해서 Outlook으로 보내줘'};
  const {ctx} = fixture({AI365_FLOW_LAUNCH:'auto', currentChatId:null,
    document: {getElementById: () => input}, openBlankChat: (text, opts) => started.push({text,opts:copy(opts)}),
    ai365AutoExecStartMulti: () => assert.fail('legacy /ask path was used')});
  vm.runInContext(fn('ai365FlowFreeSend'), ctx);
  ctx.event = {stopImmediatePropagation(){}, preventDefault(){}};
  assert.equal(vm.runInContext('ai365FlowFreeSend(event)', ctx), true);
  assert.equal(started.length, 1);
  assert.deepEqual(started[0].opts.agents, ['work','groupware']);
  assert.deepEqual(started[0].opts.scopeFiles.workers, ['email']);
  assert.equal(input.value, '');
});

test('historical agent_exec followup bypasses neither the shared stream nor selected groupware', () => {
  const sent = [];
  const question = '주문 정보를 취합해서 Outlook으로 보내줘';
  const {ctx} = fixture({currentChatId:'legacy', AI365_BACKEND_IDS:new Set(['legacy']), AI365_AUTO_CHATS:{legacy:'email'},
    chatInner:{querySelectorAll:()=>[{textContent:question}]},
    simulateAiReply:()=>assert.fail('mock reply used'), ai365AttachTake:()=>null,
    ai365AutoHandle:()=>assert.fail('email /ask interceptor used'),
    ai365GwHandle:()=>assert.fail('groupware widget interceptor used'),
    ai365StreamReply:text=>sent.push(text)});
  vm.runInContext(assignment('const ai365OrigSimulateAiReply = simulateAiReply;'), ctx);
  vm.runInContext('simulateAiReply()', ctx);
  assert.deepEqual(sent,[question]);
  vm.runInContext(fn('ai365AutoHandle'), ctx);
  assert.equal(vm.runInContext("ai365AutoHandle('followup')",ctx),false);
});

test('one-shot workflows and explicit groupware action replies keep their original priority', () => {
  let workflows=0, cards=0, streams=0;
  const {ctx} = fixture({currentChatId:'c', AI365_BACKEND_IDS:new Set(['c']),
    chatInner:{querySelectorAll:()=>[{textContent:'확인'}]}, simulateAiReply(){}, ai365AttachTake:()=>null,
    ai365FlowHandle:()=>{workflows++;return true;}, ai365GwCardHandle:()=>{cards++;return true;},
    ai365StreamReply:()=>streams++});
  vm.runInContext(assignment('const ai365OrigSimulateAiReply = simulateAiReply;'), ctx);
  vm.runInContext('simulateAiReply()',ctx);
  assert.deepEqual([workflows,cards,streams],[1,0,0]);
  ctx.ai365FlowHandle=()=>false;
  vm.runInContext('simulateAiReply()',ctx);
  assert.deepEqual([workflows,cards,streams],[1,1,0]);
});

function creatingFixture() {
  const sent=[], requests=[], wraps=[], sending=[], listeners={};
  const el={classList:{contains:()=>true},setAttribute(){}};
  const {ctx,selection}=fixture({ai365HomeScope:'사내',currentChatId:null,chats:[],AI365_BACKEND_IDS:new Set(),
    document:{createElement:()=>({...el,isConnected:false,remove(){this.isConnected=false;}}),
      addEventListener:(name,handler)=>{listeners[name]=handler;},querySelectorAll:()=>[],querySelector:()=>el},
    $ :()=>el,chatInner:{appendChild(wrap){wrap.isConnected=true;wraps.push(wrap);},
      set innerHTML(value){wraps.forEach(wrap=>{wrap.isConnected=false;});}},
    ai365AttachTake:()=>null,cancelPptGeneration(){},cancelProjThinking(){},cancelReply(){ctx.replyActive=false;},closeArtifact(){},
    ai365SetScopeLabel(){},showView(){},appendUserMessage(){},ai365T:s=>s,stickToBottom(){},renderChatLists(){},
    AI365_JSON_HEADERS:{},ai365StreamReply:(text,opts)=>sent.push({text,opts:copy({...opts,wrap:undefined})}),
    ai365GwHandle:()=>assert.fail('groupware widget intercepted first query'),console,toast(){},AbortController,
    replyActive:false,ai365Abort:null,ai365ChatCreate:null,ai365ChatCreateNo:0,AI365_QUEUE:null,AI365_FLOW_LAUNCH:null,
    ai365SetSending:on=>{ctx.replyActive=on;sending.push(on);},ai365QueueRender(){},
    finishReply:()=>assert.fail('mock finish used while creating chat')});
  ctx.setComposer=()=>{selection.agents=[];selection.files=[];selection.scope={};};
  ctx.ai365Fetch=(url,opts)=>new Promise((resolve,reject)=>{requests.push({url,opts,resolve,reject});});
  vm.runInContext(fn('ai365CancelChatCreate')+'\n'+fn('ai365QueueKey')+'\n'+fn('ai365QueueAlive')+'\n'
    +assignment('const ai365OrigCancelReply = cancelReply;')+'\n'
    +assignment('const ai365OrigFinishReply = finishReply;')+'\n'
    +assignment('openBlankChat = function (firstMessage, opts) {'),ctx);
  const queueStart=source.indexOf("document.addEventListener('keydown'",source.indexOf('/* Streaming-Enter capture'));
  vm.runInContext(source.slice(queueStart,source.indexOf('\n}, true);',queueStart)+10),ctx);
  return {ctx,selection,sent,requests,wraps,sending,listeners};
}
const tick=()=>new Promise(r=>setImmediate(r));

test('new chat creation snapshots workers/resources before reset and forwards them to first stream', async () => {
  const {ctx,sent,requests}=creatingFixture();
  vm.runInContext("openBlankChat('인보이스를 내 메일로 보내줘')",ctx);
  requests[0].resolve({id:'new-chat',title:'Invoice'});
  await tick();
  assert.equal(sent.length,1);
  assert.deepEqual(sent[0].opts.agents,['work','groupware']);
  assert.deepEqual(sent[0].opts.scopeFiles.workers,['email']);
  assert.deepEqual(sent[0].opts.scopeFiles.knowledge_files,['policy.pdf']);
});

test('creation awaits title with send guard active; repeated Enter queues into the created chat', async () => {
  const {ctx,sent,requests,listeners}=creatingFixture();
  vm.runInContext("openBlankChat('first')",ctx);
  assert.equal(ctx.replyActive,true);
  assert.equal(ctx.currentChatId,null);
  const input={id:'chatInput',value:'second'};
  listeners.keydown({key:'Enter',target:input});
  assert.equal(input.value,'');
  assert.equal(ctx.AI365_QUEUE.items[0].text,'second');
  assert.equal(requests.length,1);
  assert.equal(sent.length,0);
  requests[0].resolve({id:'created',title:'First'});
  await tick();
  assert.equal(ctx.AI365_QUEUE.chat,'created');
  assert.equal(ctx.replyActive,true);
  assert.deepEqual(sent.map(s=>s.text),['first']);
});

test('late create success cannot hijack another launcher or clear its sending state', async () => {
  const {ctx,sent,requests,wraps,listeners}=creatingFixture();
  vm.runInContext("openBlankChat('A')",ctx);
  listeners.keydown({key:'Enter',target:{id:'chatInput',value:'old queued'}});
  wraps[0].isConnected=false;
  vm.runInContext("openBlankChat('B')",ctx);
  assert.equal(requests[0].opts.signal.aborted,true);
  requests[0].resolve({id:'chat-A',title:'A'}); // an already-settled POST may still return after abort
  await tick();
  assert.equal(ctx.currentChatId,null);
  assert.equal(ctx.replyActive,true);
  assert.equal(sent.length,0);
  requests[1].resolve({id:'chat-B',title:'B'});
  await tick();
  assert.equal(ctx.currentChatId,'chat-B');
  assert.deepEqual(sent.map(s=>s.text),['B']);
  assert.notEqual(ctx.AI365_QUEUE.chat,'chat-B');
  assert.equal(vm.runInContext('ai365QueueAlive()',ctx),false);
});

test('late create failure cannot release a newer request; current failure releases the guard', async () => {
  const {ctx,requests,wraps}=creatingFixture();
  ctx.console={warn(){}};
  vm.runInContext("openBlankChat('A'); openBlankChat('B');",ctx);
  requests[0].reject(new Error('stale failure'));
  await tick();
  assert.equal(ctx.replyActive,true);
  assert.equal(wraps[1].isConnected,true);
  requests[1].reject(new Error('current failure'));
  await tick();
  assert.equal(ctx.replyActive,false);
  assert.match(wraps[1].innerHTML,/채팅 생성에 실패/);
});

test('stop while creating aborts the request and cannot start its first stream later', async () => {
  const {ctx,sent,requests,wraps,listeners}=creatingFixture();
  vm.runInContext("openBlankChat('first')",ctx);
  listeners.keydown({key:'Enter',target:{id:'chatInput',value:'second'}});
  vm.runInContext('finishReply()',ctx);
  assert.equal(ctx.replyActive,false);
  assert.equal(requests[0].opts.signal.aborted,true);
  assert.equal(wraps[0].isConnected,false);
  ctx.setTimeout=fn=>fn();
  ctx.submitFromChat=()=>assert.fail('queue drained into a chat-less mock');
  vm.runInContext(fn('ai365QueueDrainSoon')+'\nai365QueueDrainSoon()',ctx);
  assert.equal(ctx.AI365_QUEUE.items.length,1);
  requests[0].resolve({id:'stopped',title:'Stopped'});
  await tick();
  assert.equal(ctx.currentChatId,null);
  assert.equal(sent.length,0);
});

for (const outcome of ['stop','failure']) {
  test('same-screen retry after creation '+outcome+' starts the backend and preserves editable queued questions', async () => {
    const {ctx,requests,sent,listeners}=creatingFixture();
    ctx.console={warn(){}};
    vm.runInContext("openBlankChat('first')",ctx);
    listeners.keydown({key:'Enter',target:{id:'chatInput',value:'queued'}});
    if (outcome==='stop') vm.runInContext('finishReply()',ctx);
    else { requests[0].reject(new Error('unavailable')); await tick(); }
    assert.equal(ctx.replyActive,false);
    assert.equal(vm.runInContext('ai365QueueAlive()',ctx),true);
    const input={id:'chatInput',value:'retry question'};
    ctx.document.getElementById=()=>input;
    ctx.event={stopImmediatePropagation(){},preventDefault(){}};
    vm.runInContext(fn('ai365FlowFreeSend'),ctx);
    assert.equal(vm.runInContext('ai365FlowFreeSend(event)',ctx),true);
    assert.equal(requests.length,2);
    assert.equal(ctx.replyActive,true);
    requests[1].resolve({id:'retry-chat',title:'Retry'});
    await tick();
    assert.deepEqual(sent.map(s=>s.text),['retry question']);
    assert.equal(ctx.AI365_QUEUE.chat,'retry-chat');
  });
}

test('workflow progress Stop also aborts its owned pending chat creation immediately', async () => {
  const {ctx,requests,sent}=creatingFixture();
  ctx.ai365WfChipTakeForBlank=()=>({id:'wf',name:'workflow',stages:2});
  ctx.ai365FlowRunStart=run=>{ctx.AI365_FLOW_RUN=run;return run;};
  ctx.ai365FlowExpireCards=()=>{};
  ctx.ai365FlowRenderBar=()=>{};
  vm.runInContext(fn('ai365FlowEnd')+"\nopenBlankChat('first'); ai365FlowEnd();",ctx);
  assert.equal(ctx.replyActive,false);
  assert.equal(ctx.AI365_FLOW_RUN,null);
  assert.equal(ctx.ai365ChatRetry,true);
  assert.equal(requests[0].opts.signal.aborted,true);
  requests[0].resolve({id:'stopped-flow',title:'Stopped flow'});
  await tick();
  assert.equal(sent.length,0);
});

test('creation retry flag is cleared by navigation and does not take over ordinary mock chats', () => {
  const {ctx}=creatingFixture();
  ctx.ai365ChatRetry=true;
  vm.runInContext('cancelReply()',ctx);
  vm.runInContext(fn('ai365FlowFreeSend'),ctx);
  ctx.event={stopImmediatePropagation:()=>assert.fail('not a creation retry'),preventDefault(){}};
  assert.equal(vm.runInContext('ai365FlowFreeSend(event)',ctx),false);
  ctx.currentChatId='mock-demo';
  ctx.ai365ChatRetry=true;
  assert.equal(vm.runInContext('ai365FlowFreeSend(event)',ctx),false);
});
