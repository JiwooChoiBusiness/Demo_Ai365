const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const helper = fs.readFileSync(path.join(__dirname,'../static/template_chat.js'),'utf8');
// 2026-09-18: the template editor moved from the mockup's Admin Center into static/board_admin.js (Boards > Board management)
const boardAdmin = fs.readFileSync(path.join(__dirname,'../static/board_admin.js'),'utf8').split('\r').join('');
let browser;
before(async () => {browser = await chromium.launch({channel:'msedge',headless:true});});
after(async () => {await browser?.close();});
async function fixture(t) {
  const p=await browser.newPage(); t.after(()=>p.close());
  await p.setContent('<style>:root{--border:#ddd;--primary:#5554d9}body{font-family:Arial;padding:20px}.form-card{border:1px solid #ddd;padding:20px;border-radius:12px}</style><div><textarea id="homeInput"></textarea><button id="homeAttBtn">+</button></div><div id="viewChat" class="active"><div><textarea id="chatInput"></textarea><button id="chatAttBtn">+</button></div></div><div id="chat"></div>');
  await p.evaluate(()=>{
    window.currentChatId='c1'; window.AI365_ACTING_USER={no:7}; window.AI365_BACKEND_IDS=new Set(['c1','c2']);
    window.ai365Esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    window.ai365T=s=>s; window.toast=()=>{}; window.showView=()=>{};
    window.openChat=id=>{currentChatId=id;}; window.openBlankChat=()=>{};
    window.ai365StreamReply=async (message,opts)=>{window.sent={message,opts};};
    window.AI365_applyEffective=()=>{}; window.ai365FlowAlive=()=>false;
    window.ai365Fetch=async()=>({});
    window.fetch=(url,opts)=>ai365Fetch(url,opts).then(data=>({ok:true,json:async()=>data}));
    window.tpl={id:'tp1',version:3,name:'월간 영업 보고서',format:'xlsx',groups:['og9']};
  });
  await p.addScriptTag({content:helper}); return p;
}
test('selection attaches a chip without running; request consumes it once',async t=>{
  const p=await fixture(t);
  await p.evaluate(()=>AI365_templateAttach(tpl,document.getElementById('chatAttBtn')));
  assert.match(await p.locator('#ai365TemplateChip-chat').innerText(),/월간 영업 보고서/);
  assert.equal(await p.evaluate(()=>window.sent),undefined);
  assert.equal(await p.evaluate(()=>AI365_templateHandle('2월 실적으로 작성해줘')),true);
  const sent=await p.evaluate(()=>window.sent);
  assert.equal(sent.message,'2월 실적으로 작성해줘');
  assert.equal(sent.opts.docRun.template_version,3);
  assert.equal(await p.evaluate(()=>AI365_templateHandle('일반 질문')),false);
  assert.equal(await p.locator('#ai365TemplateChip-chat').isVisible(),false);
});
test('home selection, removal, chat switching and identity isolation',async t=>{
  const p=await fixture(t);
  await p.evaluate(()=>AI365_templateAttach(tpl,document.getElementById('homeAttBtn')));
  assert.equal(await p.locator('#ai365TemplateChip-home').isVisible(),true);
  await p.locator('#ai365TemplateChip-home button').click();
  assert.equal(await p.evaluate(()=>AI365_templateTake('home')),null);
  await p.evaluate(()=>{AI365_templateAttach(tpl,document.getElementById('chatAttBtn'));openChat('c2');});
  assert.equal(await p.locator('#ai365TemplateChip-chat').isVisible(),false);
  await p.evaluate(()=>openChat('c1'));
  assert.equal(await p.locator('#ai365TemplateChip-chat').isVisible(),true);
  await p.evaluate(()=>{AI365_ACTING_USER={no:12};AI365_applyEffective();});
  assert.equal(await p.locator('#ai365TemplateChip-chat').isVisible(),false);
});
test('missing inputs render a question and submit the original request with values',async t=>{
  const p=await fixture(t);
  await p.evaluate(async()=>{
    window.ai365Fetch=async()=>({template_id:'tp1',version:3,name:'보고서',format:'xlsx',question_id:'m1',
      message:'2월 실적 보고서',inputs:{},missing:[{name:'부서',required:true}]});
    await AI365_prepareTemplateMessage('2월 실적 보고서',{template_id:'tp1',template_version:3},document.getElementById('chat'),'c1');
  });
  assert.equal(await p.locator('.ai365-template-question').count(),1);
  await p.getByRole('textbox',{name:'부서'}).fill('영업팀');
  await p.getByRole('button',{name:'작성하기'}).click();
  const sent=await p.evaluate(()=>window.sent);
  assert.equal(sent.message,'2월 실적 보고서');
  assert.equal(sent.opts.docRun.template_inputs['부서'],'영업팀');
  assert.equal(sent.opts.docRun.template_question_id,'m1');
});
test('in-flight preparation cannot show another user’s template card',async t=>{
  const p=await fixture(t);
  await p.evaluate(()=>{
    ai365Fetch=()=>new Promise(resolve=>window.resolve=resolve);
    window.preparing=AI365_prepareTemplateMessage('작성',{template_id:'tp1'},document.getElementById('chat'),'c1');
    AI365_ACTING_USER={no:12};
    resolve({missing:[{name:'비밀'}],name:'이전 사용자',inputs:{}});
  });
  assert.equal(await p.evaluate(()=>preparing),null);
  assert.equal(await p.locator('.ai365-template-question').count(),0);
});
test('admin separates public/group scopes and exposes three Office upload types',async t=>{
  const p=await fixture(t);
  const a=boardAdmin.indexOf('  function bdTplDefault()');
  const b=boardAdmin.indexOf('  function bdTplPut(',a);
  assert.ok(a>=0&&b>a);
  await p.evaluate(code=>{
    window.esc=ai365Esc; window.BD_IC='';window.say=()=>{};window.bdTranslate=()=>{};window.BD={groups:['og9'],canAll:false,tpl:null};
    window.BD_FMT_LABEL={docx:'Word',xlsx:'Excel',pptx:'PPT',pdf:'PDF'};
    window.BD_STYLES={docx:[['formal','격식']],xlsx:[['blue','파랑']],pptx:[['formal','격식']]};
    window.AI365_ORG_GROUPS=[{id:'og9',name:'영업팀'},{id:'og3',name:'인사팀'}];
    window.bdActing=()=>String(AI365_ACTING_USER.no); window.bdLoad=()=>{};
    window.bdFetch=async()=>({}); window.eval(code); bdTplOpen(null);
  },boardAdmin.slice(a,b));
  assert.equal(await p.locator('[data-bt-audience] option').count(),1);
  assert.equal(await p.locator('[data-bt-group="og9"]').isChecked(),true);
  assert.equal(await p.locator('[data-bt-group="og3"]').count(),0);
  assert.equal(await p.locator('#bdTplUpload').getAttribute('accept'),'.docx,.xlsx,.pptx,.pdf');   // 2026-09-21: PDF 는 Word 양식으로 옮겨 등록 / PDFs are rebuilt as Word forms
  // super: every group (groups=null) and shared templates (canAll) / all-hands board managers get canAll too
  await p.evaluate(()=>{BD.groups=null;BD.canAll=true;bdTplOpen(null);});
  assert.equal(await p.locator('[data-bt-audience]').inputValue(),'all');
  await p.locator('[data-bt-audience]').selectOption('group');
  assert.equal(await p.locator('[data-bt-group]').count(),2);
  await p.evaluate(()=>{BD.groups=[];BD.canAll=true;bdTplOpen(null);});
  assert.deepEqual(await p.locator('[data-bt-audience] option').evaluateAll(o=>o.map(x=>x.value)),['all']);
});

// 2026-09-21: 양식 파일 중심 등록 — AI 가 읽은 항목을 확인하고, 끄기·이름 변경은 저장할 때 /remark 로 반영한다
// File-first registration: review the AI-read items; off/rename are applied through /remark on save
test('file-first registration reviews AI-read items and re-marks the form on save',async t=>{
  const p=await fixture(t);
  const a=boardAdmin.indexOf('  function bdTplDefault()');
  const b=boardAdmin.indexOf('  function bdTplPut(',a);
  await p.evaluate(code=>{
    window.esc=ai365Esc; window.BD_IC='';window.says=[];window.say=m=>says.push(m);window.bdTranslate=()=>{};window.BD={groups:null,canAll:true,tpl:null};
    window.BD_FMT_LABEL={docx:'Word',xlsx:'Excel',pptx:'PPT',pdf:'PDF'}; window.BD_STYLES={docx:[['formal','격식']]};
    window.AI365_ORG_GROUPS=[]; window.bdActing=()=>''; window.bdLoad=()=>{};
    const slot=(name,extra)=>Object.assign({key:name,name,group:name.includes('.')?name.split('.')[0]:'',type:'text',hint:'',example:'',required:false,original:'',off:false},extra||{});
    const slots=[slot('회의명',{required:true,original:'예) 주간 회의',hint:'회의 이름'}),slot('작성일'),slot('파트.파트명',{original:'1.1 파트명'}),slot('논의',{type:'list'})];
    const file=(id,list)=>({id,filename:'회의록.docx',format:'docx',auto:true,fields:list.filter(s=>!s.off).map(s=>s.name),groups:[],
      analysis:{slots:list,groups:[{name:'파트',hint:'파트별 공유'}],stats:{slots:list.filter(s=>!s.off).length,removed:3}}});
    window.calls=[];
    window.bdFetch=async(url,opt)=>{
      const body=opt&&typeof opt.body==='string'?JSON.parse(opt.body):null; calls.push({url,body});
      if(url.endsWith('/remark')) return {file:file('tf_2',slots.map(s=>s.name==='작성일'?{...s,off:true}:(s.name==='회의명'?{...s,name:'회의 제목'}:s)))};
      if(url==='/api/boards/template-files') return {file:file('tf_1',slots),analysis:{name:'주간 회의록',description:'회의 기록',instruction:'개조식'}};
      return {};
    };
    window.eval(code); bdTplOpen(null);
  },boardAdmin.slice(a,b));
  assert.equal(await p.locator('#bdTplOv .flapi-tabs').isVisible(),false);          // 탭 없이 한 화면 / one screen, no tabs
  assert.equal(await p.locator('.bd-slot-tbl').count(),0);
  await p.evaluate(()=>bdTplUpload(new File(['x'],'회의록.docx')));
  await p.locator('.bd-slot-tbl').waitFor();
  assert.equal(await p.locator('.bd-slot-tbl tbody tr.grp').count(),1);
  assert.equal(await p.locator('.bd-slot-tbl tbody tr:not(.grp)').count(),4);
  assert.equal(await p.locator('[data-bt="name"]').inputValue(),'주간 회의록');        // AI 제안으로 채워진다 / prefilled from the analysis
  assert.equal(await p.locator('[data-bt="instruction"]').inputValue(),'개조식');
  assert.equal(await p.locator('[data-bt-slot$=":required"]').count(),2);              // 묶음·목록 항목에는 필수 칸이 없다 / none for group or list items
  assert.equal(await p.locator('[data-bt="source"]').count(),0);                      // 자료 출처 3지선다는 없다 / the three-way source dropdown is gone
  await p.locator('[data-bt-lookup]').check();
  await p.locator('[data-bt-slot="1:on"]').uncheck();
  await p.locator('[data-bt-slot="0:label"]').fill('회의 제목');
  await p.locator('[data-bt-save]').click();
  await p.waitForFunction(()=>calls.some(c=>c.url==='/api/boards/templates'));
  const calls=await p.evaluate(()=>calls);
  const remark=calls.find(c=>c.url.endsWith('/tf_1/remark'));
  assert.deepEqual([remark.body.off,remark.body.rename],[['작성일'],{'회의명':'회의 제목'}]);
  const saved=calls.find(c=>c.url==='/api/boards/templates').body.template;
  assert.deepEqual([saved.mode,saved.format,saved.file_id,saved.source],['fill','docx','tf_2','internal']);   // 체크 = 항상 사내 자료 조회 / checked = always look up internal data
  assert.deepEqual(saved.sections.map(s=>s.title),['회의 제목','파트.파트명','논의']);
  assert.deepEqual(saved.inputs.map(i=>[i.name,i.required]),[['회의 제목',true]]);      // 입력 = 묶음·목록이 아닌 단일 항목만 / inputs = single items only
  assert.equal(saved.sections[0].hint,'회의 이름');
  assert.ok(!('slots' in saved)&&!('file' in saved));
});

test('canceled preparation does not render a question',async t=>{
  const p=await fixture(t);
  const result=await p.evaluate(async()=>{
    const controller=new AbortController();
    ai365Fetch=async()=>{controller.abort();return {missing:[{name:'부서'}]};};
    return AI365_prepareTemplateMessage('요청',{template_id:'tp1'},document.getElementById('chat'),'c1',controller.signal);
  });
  assert.equal(result,null);
  assert.equal(await p.locator('.ai365-template-question').count(),0);
});

test('version and permission errors retain the server’s actionable explanation',async t=>{
  const p=await fixture(t);
  const error=await p.evaluate(async()=>{
    fetch=async()=>({ok:false,json:async()=>({detail:'템플릿이 변경됐습니다. 다시 선택해 주세요'})});
    try {await AI365_prepareTemplateMessage('요청',{template_id:'tp1'},document.getElementById('chat'),'c1');}
    catch(err){return err.message;}
  });
  assert.equal(error,'템플릿이 변경됐습니다. 다시 선택해 주세요');
});
