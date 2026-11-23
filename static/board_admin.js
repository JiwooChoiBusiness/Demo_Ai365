/* =====================================================================
   게시판 관리(2026-09-18) — 사이드바 [게시판] 메뉴 안의 관리 화면 본문(리소스 센터 › 리소스 관리와 같은 위치감). 지금은 문서 템플릿만.
   관리 센터 "게시판 설정" 카드(탭: 게시판·템플릿·통계)를 없애면서 템플릿 탭을 이 파일로 옮겼다(목업의 bd* 코드 이전, 게시판·통계 탭은 폐지).
   화면 껍데기(제목·뒤로·[+ 템플릿 추가])는 adapter.js 의 게시판 IIFE 가 그리고, 여기는 목록 + 등록/수정 패널(#bdTplOv)을 맡는다.
   권한: 서버 /api/boards/templates?all=1 이 내가 관리할 수 있는 템플릿만 돌려준다 — 그룹 전용은 그 그룹 게시판 전부의 관리 권한,
   전체 공용은 전체 게시판의 관리 권한(can_all), 슈퍼는 전부(groups = null). 화면은 이 응답만 믿는다.
   **등록 = 양식 파일 중심(2026-09-21 사용자 지시 "문서 등록 위주, 양식 파일 필수, 올린 원본을 최대한 참조")**: 한 화면에서 ① 양식 파일 올리기
   → ② 채울 항목 확인 → ③ 기본 정보 → ④ 작성 지침. Word · Excel · PowerPoint 는 표시({{ }}) 없이 올리면 서버가 AI 로 채울 자리를 찾아 주고(자동 인식, PDF 는 같은 구조의 Word 로 옮겨서),
   관리자는 항목을 끄거나 이름·설명·필수 여부만 고친다(끄기·이름 변경은 저장·샘플 확인 때 /remark 로 원본에서 표시본을 다시 만든다).
   이미 표시가 든 파일은 종전처럼 표시를 읽는다. 자료 출처는 "항상 사내 자료 조회" 체크 하나(요청·대화는 항상 재료). 파일 없는 옛 "구조 참고" 템플릿은 종전 탭 편집기(bdTplRenderLegacy)로만 고친다.
   목업의 전역 스타일(.flapi-* 패널, .tok-table·.conn-* 표, .fl-mini 버튼)을 그대로 쓴다.
   Board management (2026-09-18) — the body of the management screen inside the sidebar [게시판] menu. Document templates only.
   The page shell (title, back, [+ Add template]) is drawn by the board IIFE in adapter.js; this file owns the list and the
   create/edit panel (#bdTplOv). Permissions: /api/boards/templates?all=1 returns only templates I can manage. **Registration is
   file-first (user decision 2026-09-21: upload required, follow the uploaded original as closely as possible)**: one screen —
   ① upload the form → ② review the fill-in items → ③ basics → ④ writing guide. A Word file without {{ }} markers is analysed by the
   server (AI finds the fill-in places); the admin only turns items off or edits names, hints and required flags (off/rename are
   re-applied from the original through /remark on save or sample). Excel, PowerPoint and already-marked files are read as before.
   Older file-less "outline" templates are edited only through the previous tabbed editor (bdTplRenderLegacy).
===================================================================== */
(function ai365BoardAdmin() {
  var BD={templates:[], groups:null, canAll:false, usage:{}, tpl:null, root:null};
  var BD_FMT_LABEL={docx:'Word', pptx:'PPT', xlsx:'Excel', pdf:'PDF'};
  var BD_STYLES={docx:[['formal','격식'],['light','밝게'],['dark','진하게'],['compact','간결']], pptx:[['dark','진하게'],['light','밝게'],['formal','격식'],['blue','블루'],['compact','간결'],['edu','교육']], pdf:[['formal','격식'],['light','밝게'],['dark','진하게'],['compact','간결']], xlsx:[['blue','블루'],['green','그린'],['mono','모노']]};
  var BD_IC='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></svg>';

  (function css(){
    var s=document.createElement('style');
    s.textContent='.bd-chk{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;color:var(--ink-2);white-space:nowrap;margin-right:8px;}'
      +'.bd-file{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}'   /* 원본 양식 파일: 스타일 버튼 + 파일명 / source form file: styled button + name */
      +'.bd-file-in{position:absolute;width:1px;height:1px;opacity:0;overflow:hidden;clip:rect(0 0 0 0);}'
      +'.bd-file-name{font-size:12.5px;color:var(--muted);}'
      +'.bd-grouplist{display:flex;flex-wrap:wrap;gap:8px 14px;padding:6px 0;}'
      +'.bd-sec-tbl input{width:100%;}'
      /* 양식 파일 중심 등록(2026-09-21) / file-first registration */
      +'.bd-drop{border:1.5px dashed var(--border);border-radius:12px;padding:16px 18px;background:#FBFBFD;display:flex;align-items:center;gap:14px;flex-wrap:wrap;}'
      +'.bd-drop.has{border-style:solid;background:#fff;}'
      +'.bd-drop .bd-file-btn{border:1.5px solid var(--primary);border-radius:9px;padding:7px 14px;font-size:13px;font-weight:700;color:var(--primary);cursor:pointer;background:#fff;}'
      +'.bd-drop.busy .bd-file-btn{opacity:.5;cursor:default;}'
      +'.bd-fname{font-size:13.5px;font-weight:700;color:var(--ink);word-break:break-all;}'
      +'.bd-fmeta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:3px;}'
      +'.bd-fmeta b{color:var(--ink);font-weight:700;}'
      +'.bd-tag{display:inline-block;font-size:11px;font-weight:700;border-radius:6px;padding:2px 7px;background:#EEF0FF;color:var(--primary);white-space:nowrap;}'
      +'.bd-tag.g{background:#E1F5EE;color:#0F6E56;}'
      +'.bd-tag.m{background:#F1F2F6;color:var(--muted);}'
      +'.bd-busy{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-2);}'
      +'.bd-busy:before{content:"";width:14px;height:14px;border-radius:50%;border:2px solid var(--border);border-top-color:var(--primary);animation:bdspin .8s linear infinite;}'
      +'@keyframes bdspin{to{transform:rotate(360deg);}}'
      +'@media (prefers-reduced-motion:reduce){.bd-busy:before{animation:none;}}'
      +'.bd-slot-tbl td{vertical-align:middle;}'
      +'.bd-slot-tbl tr.off td{opacity:.45;}'
      +'.bd-slot-tbl tr.off td:first-child{opacity:1;}'
      +'.bd-slot-tbl .grp td{background:#F8F9FC;font-size:12.5px;font-weight:700;color:var(--ink);padding:7px 10px;}'
      +'.bd-slot-tbl .grp td span.h{font-weight:500;color:var(--muted);margin-left:6px;}'
      +'.bd-slot-name{display:flex;align-items:center;gap:6px;min-width:0;}'
      +'.bd-slot-name input{flex:1;min-width:0;font-weight:600;}'
      +'.bd-slot-name .ro{font-weight:600;color:var(--ink);padding:6px 8px;word-break:break-all;}'
      +'.bd-slot-orig{font-size:12px;color:var(--muted);padding:6px 8px;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
      +'.bd-step{display:flex;align-items:center;gap:8px;}'
      +'.bd-step i{font-style:normal;width:20px;height:20px;border-radius:50%;background:var(--primary);color:#fff;font-size:11.5px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;}'
      +'.bd-wait{color:var(--muted);font-size:13px;padding:14px 2px;}'
      +'#bdTplOv textarea{font-family:inherit;}';
    document.head.appendChild(s);
  })();

  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function say(msg){ if(typeof toast==='function') toast(msg); }
  function bdActing(){ return window.AI365_ACTING_USER ? String(window.AI365_ACTING_USER.no) : ''; }
  function bdFetch(url, opt){ return fetch(url, opt).then(function(r){ return r.json().then(function(j){ if(!r.ok) throw new Error((j&&j.detail)||('HTTP '+r.status)); return j; }); }); }
  function bdGroupName(gid){ var g=(window.AI365_ORG_GROUPS||[]).find(function(x){ return x.id===gid; }); return g?g.name:gid; }
  function bdTranslate(el){ if(el && typeof window.AI365_translateRoot==='function') window.AI365_translateRoot(el); }

  /* ── 목록 / list ── */
  function bdLoad(){
    var body=BD.root; if(!body) return;
    body.innerHTML='<div style="color:var(--muted);font-size:13px;padding:20px 0">불러오는 중…</div>';
    var owner=bdActing();
    bdFetch('/api/boards/templates?all=1&acting_user_id='+encodeURIComponent(owner)).then(function(d){
      if(owner!==bdActing() || BD.root!==body) return;   // 뷰애즈 신원이 바뀌었으면 버린다 / drop a response from a previous identity
      BD.templates=d.templates||[]; BD.groups=d.groups||null; BD.canAll=!!d.can_all; BD.usage=d.usage||{};
      bdRenderTemplates();
    }).catch(function(e){ if(BD.root===body) body.innerHTML='<div class="conn-empty">'+esc(e.message||'템플릿을 불러오지 못했습니다.')+'</div>'; bdTranslate(body); });
  }
  function bdTplUsage(id){ return BD.usage[id]||{uses:0,last_used:''}; }
  function bdRenderTemplates(){
    var body=BD.root; if(!body) return;
    if(!BD.templates.length){ body.innerHTML='<div class="conn-empty">등록된 템플릿이 없습니다. [+ 템플릿 추가]로 회사 양식 파일을 올리면 구성원의 + 메뉴에 "템플릿 가져오기"가 생깁니다.</div>'; bdTranslate(body); return; }
    var rows=BD.templates.map(function(t){
      var u=bdTplUsage(t.id);
      var how=t.mode==='outline'?'<span>구조 참고</span>':('<span>원본 양식 채우기</span>'+((t.file&&t.file.auto)?' <span class="bd-tag">AI 인식</span>':''));
      return '<tr data-bdtplrow="'+esc(t.id)+'"><td><div class="conn-name">'+esc(t.name)+'</div><div class="conn-desc">'+esc(t.description||'')+'</div></td>'
        +'<td>'+((t.groups||[]).length?esc((t.groups||[]).map(bdGroupName).join(', ')):'<span>전체 공용</span>')+'</td>'
        +'<td>'+esc(BD_FMT_LABEL[t.format]||t.format)+'</td><td>'+how+'</td><td>v'+(t.version||1)+'</td>'
        +'<td>'+(t.status==='active'?'<span class="fl-apist ok">사용</span>':'<span class="fl-apist unset">중지</span>')+'</td>'
        +'<td>'+(u.uses||0)+'</td><td>'+esc(String(u.last_used||'').replace('T',' ').slice(0,16)||'-')+'</td>'
        +'<td class="conn-acts"><button type="button" class="fl-mini" data-bdtpledit="'+esc(t.id)+'">수정</button><button type="button" class="fl-mini" data-bdtplcopy="'+esc(t.id)+'">복제</button><button type="button" class="fl-mini" data-bdtpltoggle="'+esc(t.id)+'">'+(t.status==='active'?'중지':'사용')+'</button><button type="button" class="fl-mini danger" data-bdtpldel="'+esc(t.id)+'">삭제</button></td></tr>';
    }).join('');
    body.innerHTML='<div class="tok-table-wrap"><table class="tok-table conn-table"><thead><tr><th scope="col">이름</th><th scope="col">적용 그룹</th><th scope="col">종류</th><th scope="col">방식</th><th scope="col">버전</th><th scope="col">상태</th><th scope="col">30일 사용</th><th scope="col">최근 사용</th><th scope="col"></th></tr></thead><tbody>'+rows+'</tbody></table></div>'
      +'<p class="flapi-hint" style="margin-top:10px">원본 양식 채우기는 올린 파일의 서식을 그대로 두고 채울 자리에만 내용을 넣습니다. Word · Excel · PowerPoint 파일은 그대로 올리면 AI가 채울 자리를 찾습니다.</p>'
      +'<p class="flapi-hint">관리 권한이 있는 게시판의 템플릿만 보입니다.</p>';   // 문장마다 따로 둔다(EN 사전은 텍스트 노드 전체 일치) / one node per sentence for the exact-match dictionary
    bdTranslate(body);
  }

  /* ── 등록/수정 패널(API 설정 패널과 같은 오른쪽 패널) / create-edit panel (same right-hand panel as the API settings) ── */
  function bdTplDefault(){ return {name:'', description:'', groups:[], format:'docx', mode:'fill', sections:[], inputs:[], slots:[], instruction:'', source:'context', length:6, style:'formal', language:'ko', status:'active'}; }
  /* 채울 항목 목록(화면 상태) — 파일에서 읽은 항목 + 템플릿에 저장된 설명·필수·기본값을 이름으로 합친다.
     자동 인식 파일이면 분석 결과(원본 글·목록 여부·묶음·꺼짐)를 같이 싣는다. key = 서버 계획의 원래 이름(이름을 바꿔도 유지).
     The fill-in item list (UI state): items read from the file merged by name with the saved hints, required flags and defaults;
     auto-read files also carry the analysis (original text, list type, group, off). key = the plan's original name. */
  function bdSlotsFrom(file, d, prev){
    var keep={}; (prev||[]).forEach(function(s){ keep[s.name]=s; });
    var hint={}, inp={};
    (d.sections||[]).forEach(function(s){ if(s&&s.title) hint[s.title]=s.hint||''; });
    (d.inputs||[]).forEach(function(x){ if(x&&x.name) inp[x.name]=x; });
    var ana=(file&&file.analysis&&file.analysis.slots)||null;
    var list=ana?ana.map(function(s){ return {key:s.key||s.name, name:s.name, group:s.group||'', type:s.type||'text', original:s.original||'', example:s.example||'', hint:s.hint||'', required:!!s.required, off:!!s.off}; })
      :((file&&file.fields)||[]).map(function(n){ return {key:n, name:n, group:n.indexOf('.')>=0?n.split('.')[0]:'', type:'text', original:'', example:'', hint:'', required:false, off:false}; });
    return list.map(function(s){
      var k=keep[s.name]||{}, i=inp[s.name];
      return {key:s.key, name:s.name, group:s.group, type:s.type, original:s.original,
        example:(i&&i.example)||k.example||s.example||'',
        hint:(s.name in hint)?(hint[s.name]||s.hint):(k.hint!==undefined?k.hint:s.hint),
        required:i?i.required!==false:(k.required!==undefined?k.required:s.required),
        def:(i&&i['default'])||k.def||'', off:s.off};
    });
  }
  function bdTplOpen(t){
    var d=t?JSON.parse(JSON.stringify(t)):bdTplDefault();
    if(t){ delete d.id; delete d.created; delete d.updated; delete d.version; }
    // 새 템플릿의 기본 범위: 전체 공용을 만들 수 있으면 전체, 아니면 내가 관리하는 첫 그룹 / default scope of a new template
    if(!t && !BD.canAll && BD.groups && BD.groups.length) d.groups=[BD.groups[0]];
    d.audience=(d.groups||[]).length?'group':'all';
    var legacy=!!(t && t.mode==='outline');   // 파일 없는 옛 구조 참고 템플릿 → 종전 탭 편집기 / older file-less templates keep the tabbed editor
    if(!legacy) d.slots=bdSlotsFrom(d.file, d, null);
    BD.tpl={id:t?t.id:null, draft:d, tab:'basic', legacy:legacy};
    bdTplEl().classList.add('open'); bdTplRender();
  }
  function bdTplClose(){ if(bdTplOv) bdTplOv.classList.remove('open'); BD.tpl=null; }
  var bdTplOv=null;
  function bdTplEl(){
    if(bdTplOv) return bdTplOv;
    bdTplOv=document.createElement('div'); bdTplOv.className='flapi-ov'; bdTplOv.id='bdTplOv';
    bdTplOv.innerHTML='<div class="flapi-panel" role="dialog" aria-label="템플릿 등록">'
      +'<div class="flapi-head"><span class="flapi-ic">'+BD_IC+'</span><div><div class="flapi-tt">템플릿 등록</div><div class="flapi-sub">그룹 구성원이 파일을 만들 때 기준으로 쓰는 문서 양식입니다.</div></div><button type="button" class="flapi-x" data-bt-close aria-label="닫기">✕</button></div>'
      +'<div class="flapi-tabs"><button type="button" data-bt-tab="basic">기본</button><button type="button" data-bt-tab="form">양식</button><button type="button" data-bt-tab="guide">지침</button><button type="button" data-bt-tab="preview">미리보기</button></div>'
      +'<div class="flapi-body" id="bdTplBody"></div>'
      +'<div class="flapi-foot"><span class="sp"></span><button type="button" data-bt-cancel>취소</button><button type="button" class="pri" data-bt-save>저장</button></div></div>';
    document.body.appendChild(bdTplOv);
    bdTplOv.addEventListener('click', function(e){ var t;
      if(e.target.closest('[data-bt-close]')||e.target.closest('[data-bt-cancel]')){ bdTplClose(); return; }
      if(e.target.closest('[data-bt-save]')){ bdTplSave(); return; }
      if(e.target.closest('[data-bt-sample]')){ bdTplSample(); return; }
      if(e.target.closest('[data-bt-reread]')){ if(BD.tpl&&BD.tpl.lastFile) bdTplUpload(BD.tpl.lastFile); return; }
      if((t=e.target.closest('[data-bt-tab]'))){ BD.tpl.tab=t.dataset.btTab; bdTplRender(); return; }
      if(e.target.closest('[data-bt-secadd]')){ BD.tpl.draft.sections.push({title:'', hint:''}); bdTplRender(); return; }
      if((t=e.target.closest('[data-bt-secdel]'))){ BD.tpl.draft.sections.splice(+t.dataset.btSecdel,1); bdTplRender(); return; }
      if((t=e.target.closest('[data-bt-secup]'))){ var i=+t.dataset.btSecup, s=BD.tpl.draft.sections; if(i>0){ var x=s.splice(i,1)[0]; s.splice(i-1,0,x); bdTplRender(); } return; }
      if((t=e.target.closest('[data-bt-secdn]'))){ var j=+t.dataset.btSecdn, s2=BD.tpl.draft.sections; if(j<s2.length-1){ var y=s2.splice(j,1)[0]; s2.splice(j+1,0,y); bdTplRender(); } return; }
      if(e.target.closest('[data-bt-inadd]')){ BD.tpl.draft.inputs.push({name:'', description:'', example:'', 'default':'', required:true}); bdTplRender(); return; }
      if((t=e.target.closest('[data-bt-indel]'))){ BD.tpl.draft.inputs.splice(+t.dataset.btIndel,1); bdTplRender(); return; }
    });
    bdTplOv.addEventListener('input', function(e){ var t=e.target, d=BD.tpl&&BD.tpl.draft; if(!d) return;
      if(t.dataset.bt&&t.tagName!=='SELECT'){ d[t.dataset.bt]=(t.type==='number')?(+t.value||0):t.value; return; }
      if(t.dataset.btSlot!==undefined&&t.type!=='checkbox'){ var sp=t.dataset.btSlot.split(':'), sl=d.slots[+sp[0]]; if(sl) sl[sp[1]]=t.value; return; }
      if(t.dataset.btSec!==undefined){ var p=t.dataset.btSec.split(':'), row=d.sections[+p[0]]; if(row) row[p[1]]=t.value; return; }
      if(t.dataset.btIn!==undefined&&t.type!=='checkbox'){ var q=t.dataset.btIn.split(':'), r2=d.inputs[+q[0]]; if(r2) r2[q[1]]=t.value; return; }
    });
    bdTplOv.addEventListener('change', function(e){ var t=e.target, d=BD.tpl&&BD.tpl.draft; if(!d) return;
      if(t.id==='bdTplUpload'){ bdTplUpload(t.files&&t.files[0]); return; }
      if(t.dataset.btLookup!==undefined){ d.source=t.checked?'internal':'context'; return; }
      if(t.dataset.btAudience!==undefined){ d.audience=t.value; if(t.value==='all') d.groups=[]; bdTplRender(); return; }
      if(t.dataset.btGroup){ var gid=t.dataset.btGroup, ix=d.groups.indexOf(gid); if(t.checked&&ix<0) d.groups.push(gid); if(!t.checked&&ix>=0) d.groups.splice(ix,1); return; }
      if(t.dataset.btSlot!==undefined&&t.type==='checkbox'){ var sp=t.dataset.btSlot.split(':'), sl=d.slots[+sp[0]]; if(!sl) return;
        if(sp[1]==='on'){ sl.off=!t.checked; bdTplRender(); } else sl[sp[1]]=!!t.checked; return; }
      if(t.dataset.bt&&t.tagName==='SELECT'){ d[t.dataset.bt]=t.value; if(t.dataset.bt==='format'){ var st=BD_STYLES[d.format]||[]; if(!st.some(function(x){ return x[0]===d.style; })) d.style=st.length?st[0][0]:'formal'; d.length=Math.min(Math.max(d.length||6, d.format==='xlsx'?5:2), d.format==='xlsx'?100:15); bdTplRender(); } return; }
      if(t.dataset.btIn!==undefined&&t.type==='checkbox'){ var q=t.dataset.btIn.split(':'), r2=d.inputs[+q[0]]; if(r2) r2[q[1]]=!!t.checked; }
    });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape'&&BD.tpl&&bdTplOv.classList.contains('open')) bdTplClose(); });
    return bdTplOv;
  }
  // 사용 범위 선택지: 전체 공용은 전체 게시판 관리 권한(can_all)이 있을 때만, 그룹 전용은 관리하는 그룹이 있을 때만(슈퍼 = groups null = 전 그룹)
  // Scope options: "shared" needs manage on the all-hands board (can_all); "group" needs a managed group (super = groups null = every group)
  function bdTplCanGroup(){ return BD.groups===null || (BD.groups||[]).length>0; }
  function bdTplGroupsHtml(d){
    var all=window.AI365_ORG_GROUPS||[];
    var allowed=BD.groups?all.filter(function(g){ return BD.groups.indexOf(g.id)>=0; }):all;
    if(!allowed.length) return '<div class="flapi-hint">그룹 목록을 불러오지 못했습니다.</div>';
    return '<div class="bd-grouplist">'+allowed.map(function(g){ return '<label class="bd-chk"><input type="checkbox" data-bt-group="'+esc(g.id)+'"'+((d.groups||[]).indexOf(g.id)>=0?' checked':'')+'> '+esc(g.name)+'</label>'; }).join('')+'</div>'
      +'<div class="flapi-hint">'+(BD.groups?'관리 권한이 있는 그룹만 고를 수 있습니다.':'그룹 전용 템플릿은 적용 그룹을 하나 이상 선택해 주세요.')+'</div>';
  }
  function bdTplScopeHtml(d){
    return '<div class="flapi-field"><label>사용 범위</label><select data-bt-audience>'
      +(BD.canAll?'<option value="all"'+(d.audience==='all'?' selected':'')+'>전체 공용</option>':'')
      +(bdTplCanGroup()?'<option value="group"'+(d.audience==='group'?' selected':'')+'>그룹 전용</option>':'')+'</select></div>'
      +(d.audience==='group'?'<div class="flapi-field"><label>적용 그룹</label>'+bdTplGroupsHtml(d)+'</div>':'<div class="flapi-hint">전체 사용자가 채팅의 + 버튼에서 가져올 수 있습니다.</div>');
  }
  function bdTplPreviewText(d, sample){
    var lines=['[문서 템플릿: '+(d.name||'(이름 없음)')+'] 아래 항목 순서와 구성을 지켜 작성한다. 항목을 빼거나 새로 만들지 않는다.'];
    lines.push('[출력 언어] '+(d.language||'ko')+'. 지정된 항목 제목은 유지하고 본문은 이 언어로 작성한다.');   // 서버 template_prompt 와 동일 / same as the server prompt
    (d.sections||[]).forEach(function(s,i){ if(s.title) lines.push((i+1)+'. '+s.title+(s.hint?' — '+s.hint:'')); });
    if(d.instruction) lines.push('[작성 지침] '+d.instruction);
    var vals=(d.inputs||[]).filter(function(x){ return x.name; }).map(function(x){ return '- '+x.name+': '+(sample?(x.example||x['default']||'(사용자 입력)'):(x['default']||'(사용자 입력)')); });
    if(vals.length) lines.push('[입력값]\n'+vals.join('\n'));
    return lines.join('\n');
  }
  function bdStep(n, label, req){ return '<div class="flapi-sec bd-step"><i>'+n+'</i><span>'+label+'</span>'+(req?' <span class="req" style="color:#E5484D">*</span>':'')+'</div>'; }
  /* ① 양식 파일 — 파일 입력(#bdTplUpload)은 숨긴 채 스타일 버튼으로 연다(브라우저 테스트가 id·accept 를 검사한다)
     ① The form file — the native input (#bdTplUpload) stays hidden behind a styled button (the browser test checks its id and accept) */
  function bdTplFileHtml(d){
    var f=d.file, busy=!!BD.tpl.uploading, ana=f&&f.analysis;
    var h='<div class="bd-drop'+(f?' has':'')+(busy?' busy':'')+'"><input id="bdTplUpload" class="bd-file-in" type="file" accept=".docx,.xlsx,.pptx,.pdf"'+(busy?' disabled':'')+'>';
    if(busy) h+='<span class="bd-busy">AI가 양식을 읽고 있습니다. 잠시만 기다려 주세요.</span>';
    else if(!f) h+='<label for="bdTplUpload" class="bd-file-btn">양식 파일 선택</label><span class="bd-file-name">선택된 파일 없음</span>';
    else {
      var live=(d.slots||[]).filter(function(s){ return !s.off; }).length, grp={}; (d.slots||[]).forEach(function(s){ if(s.group&&!s.off) grp[s.group]=1; });
      h+='<div style="flex:1;min-width:0"><div class="bd-fname">'+esc(f.filename)+'</div><div class="bd-fmeta"><span class="bd-tag m">'+esc(BD_FMT_LABEL[f.format]||f.format)+'</span>'
        +(f.converted_from==='pdf'?'<span class="bd-tag m">PDF에서 옮김</span>':'')
        +(f.auto?'<span class="bd-tag">AI 인식</span>':'<span class="bd-tag g">표시 읽음</span>')
        +'<span>채울 항목</span><b>'+live+'</b>'+(Object.keys(grp).length?'<span>반복 묶음</span><b>'+Object.keys(grp).length+'</b>':'')
        +((ana&&ana.stats&&ana.stats.removed)?'<span>정리한 중복 줄</span><b>'+ana.stats.removed+'</b>':'')+'</div></div>'
        +'<button type="button" class="fl-mini" data-bt-sample>샘플 파일 확인</button>'
        +((f.auto&&BD.tpl.lastFile)?'<button type="button" class="fl-mini" data-bt-reread>다시 읽기</button>':'')
        +'<label for="bdTplUpload" class="bd-file-btn">파일 바꾸기</label>';
    }
    h+='</div>'+((f&&f.converted_from==='pdf')?'<div class="flapi-hint" style="color:#B45309">PDF는 원본 그대로 채울 수 없어 같은 구조의 Word 양식으로 옮겼습니다. 결과 파일은 Word로 만들어지며 그림·선 장식은 옮겨지지 않습니다. 원본 Word 파일이 있으면 그 파일을 올리는 편이 더 정확합니다.</div>':'')
      +'<div class="flapi-hint">Word · Excel · PowerPoint 회사 양식을 그대로 올리면 AI가 채울 자리를 찾습니다(10~40초). 원본의 글꼴·표·순서는 그대로 둡니다.</div>'
      +'<div class="flapi-hint">PDF는 같은 구조의 Word 양식으로 옮겨 등록합니다(결과 파일은 Word). 이미 {{보고기간}}처럼 표시를 넣은 파일은 그 표시를 그대로 읽습니다. 10MB 이하.</div>';
    return h;
  }
  /* ② 채울 항목 — 파일에서 읽은 항목만(추가·삭제 없음). 자동 인식 파일은 끄기·이름 변경 가능, 필수·기본값은 묶음 밖 항목만.
     ② Fill-in items — only what the file holds (no add/remove). Auto-read files allow off/rename; required/default apply outside groups. */
  function bdTplSlotsHtml(d){
    var f=d.file, auto=!!(f&&f.auto), slots=d.slots||[], ghint={}, gcap={};
    ((f&&f.analysis&&f.analysis.groups)||[]).forEach(function(g){ ghint[g.name]=g.hint||''; gcap[g.name]=g.capacity||0; });
    if(!f) return '<div class="bd-wait">양식 파일을 올리면 채울 항목이 여기에 나타납니다.</div>';
    var cols=auto?6:4, last=null;
    var h='<table class="flapi-tbl bd-slot-tbl"><thead><tr>'+(auto?'<th style="width:44px">사용</th>':'')+'<th style="width:24%">항목</th>'+(auto?'<th style="width:20%">원본에 있던 글</th>':'')
      +'<th>설명 (무엇을 쓰는 자리인지)</th><th style="width:52px">필수</th><th style="width:16%">기본값</th></tr></thead><tbody>';
    slots.forEach(function(s,i){
      if(s.group!==last && s.group){ h+='<tr class="grp"><td colspan="'+cols+'"><span>'+esc(s.group)+'</span> <span class="bd-tag m">반복 묶음</span>'+(gcap[s.group]?' <span class="bd-tag m">원본 행 수</span> <b>'+gcap[s.group]+'</b>':'')+'<span class="h">'+esc(ghint[s.group]||'')+'</span></td></tr>'; }
      last=s.group;
      var field=s.group?s.name.slice(s.group.length+1):s.name, solo=!s.group&&s.type!=='list';   // 필수·기본값은 한 줄짜리 단일 항목만(묶음·목록은 AI 가 자료에서 채운다) / required and default only for single one-line items
      h+='<tr'+(s.off?' class="off"':'')+'>'
        +(auto?'<td style="text-align:center"><input type="checkbox" data-bt-slot="'+i+':on"'+(s.off?'':' checked')+' aria-label="사용"></td>':'')
        +'<td><div class="bd-slot-name">'+(auto&&!s.off?'<input type="text" maxlength="30" data-bt-slot="'+i+':label" value="'+esc(s.label!==undefined?s.label:field)+'">':'<span class="ro">'+esc(field)+'</span>')
        +(s.type==='list'?'<span class="bd-tag g">목록</span>':'')+'</div></td>'
        +(auto?'<td><div class="bd-slot-orig" title="'+esc(s.original)+'">'+esc(s.original||'')+'</div></td>':'')
        +'<td><input type="text" maxlength="200" data-bt-slot="'+i+':hint" value="'+esc(s.hint||'')+'"'+(s.off?' disabled':'')+' placeholder="예: 지난주 대비 증감을 수치로"></td>'
        +'<td style="text-align:center">'+(solo?'<input type="checkbox" data-bt-slot="'+i+':required"'+(s.required?' checked':'')+(s.off?' disabled':'')+' aria-label="필수">':'')+'</td>'
        +'<td>'+(solo?'<input type="text" maxlength="120" data-bt-slot="'+i+':def" value="'+esc(s.def||'')+'"'+(s.off?' disabled':'')+'>':'')+'</td></tr>';
    });
    h+='</tbody></table>'
      +(auto?'<div class="flapi-hint">끈 항목은 원본에 있던 글 그대로 남습니다. 이름을 바꾸거나 끈 내용은 저장하거나 샘플 파일을 확인할 때 양식에 반영됩니다.</div>':'')
      +'<div class="flapi-hint">필수 항목은 요청에 값이 없으면 파일을 만들기 전에 질문 카드로 묻습니다. 기본값이 있으면 묻지 않습니다.</div>'
      +'<div class="flapi-hint">반복 묶음은 내용 수만큼 줄이나 절이 늘어나고, 목록은 글머리표가 줄 수만큼 늘어납니다.</div>'
      +'<div class="flapi-hint">Excel 과 슬라이드 표의 반복 묶음은 행을 늘리지 않고 원본에 있는 행 수까지만 위에서부터 채웁니다(수식·인쇄 영역·슬라이드 크기 보존).</div>';
    return h;
  }
  function bdTplRender(){
    if(!BD.tpl||!bdTplOv) return;
    var d=BD.tpl.draft;
    bdTplOv.querySelector('.flapi-tt').textContent=BD.tpl.id?'템플릿 수정':'템플릿 등록';
    bdTplOv.querySelector('.flapi-tabs').style.display=BD.tpl.legacy?'':'none';
    if(BD.tpl.legacy){ bdTplRenderLegacy(); return; }
    var h=bdStep(1,'양식 파일',true)+bdTplFileHtml(d)
      +bdStep(2,'채울 항목')+bdTplSlotsHtml(d)
      +bdStep(3,'기본 정보')
      +'<div class="flapi-field"><label>템플릿 이름 <span class="req">*</span></label><input type="text" data-bt="name" maxlength="80" value="'+esc(d.name||'')+'" placeholder="예: 주간 업무 보고"></div>'
      +'<div class="flapi-field"><label>한 줄 설명 (구성원의 + 메뉴에 보입니다)</label><input type="text" data-bt="description" maxlength="300" value="'+esc(d.description||'')+'" placeholder="예: 팀 주간 보고 표준 양식. 성과·이슈·다음 주 계획 순서"></div>'
      +bdTplScopeHtml(d)
      +'<div class="flapi-field" style="max-width:200px;margin-top:10px"><label>상태</label><select data-bt="status"><option value="active"'+(d.status!=='off'?' selected':'')+'>사용</option><option value="off"'+(d.status==='off'?' selected':'')+'>중지</option></select></div>'
      +bdStep(4,'작성 지침')
      +'<div class="flapi-field"><label>작성 지침 (최우선 규칙)</label><textarea data-bt="instruction" maxlength="2000" rows="4" placeholder="예: 결론 먼저, 수치는 표로, 존댓말 평서문">'+esc(d.instruction||'')+'</textarea></div>'
      // 자료 출처(2026-09-21 개편): 요청과 대화는 항상 재료 → 3지선다 대신 "항상 사내 자료 조회" 체크 하나(source = internal | context)
      // Material source (reworked): the request and the conversation are always material, so one "always look up internal data" checkbox replaces the dropdown
      +'<label class="bd-chk" style="margin-top:4px"><input type="checkbox" data-bt-lookup'+(d.source==='internal'?' checked':'')+'> <span>항상 사내 자료를 조회해서 채웁니다</span></label>'
      +'<div class="flapi-hint">요청 문장과 그 채팅의 대화 내용은 항상 재료로 씁니다. 매출·실적처럼 사내 데이터가 꼭 필요한 문서만 켜 두세요.</div>'
      +'<div class="flapi-hint">꺼 두어도 구성원이 요청에서 "사내 자료를 조회해서"처럼 말하면 그때는 조회합니다. 찾은 자료가 없으면 채울 수 있는 곳만 채우고 알려 줍니다.</div>';
    document.getElementById('bdTplBody').innerHTML=h;
    bdTranslate(bdTplOv);
  }
  /* 파일 없는 옛 "구조 참고" 템플릿 편집(항목·지침을 손으로 적는 방식) — 새로 만들 수는 없고 있는 것만 고친다(2026-09-21)
     Editor for older file-less "outline" templates (hand-typed sections and guide) — existing ones only, no new ones */
  function bdTplRenderLegacy(){
    var d=BD.tpl.draft, tab=BD.tpl.tab;
    bdTplOv.querySelectorAll('[data-bt-tab]').forEach(function(b){ b.classList.toggle('on', b.dataset.btTab===tab); });
    var h='';
    if(tab==='basic'){
      h+='<div class="flapi-field"><label>템플릿 이름 <span class="req">*</span></label><input type="text" data-bt="name" maxlength="80" value="'+esc(d.name||'')+'" placeholder="예: 주간 업무 보고"></div>'
        +'<div class="flapi-field"><label>한 줄 설명 (구성원의 + 메뉴에 보입니다)</label><input type="text" data-bt="description" maxlength="300" value="'+esc(d.description||'')+'" placeholder="예: 팀 주간 보고 표준 양식. 성과·이슈·다음 주 계획 순서"></div>'
        +'<div class="flapi-row2"><div class="flapi-field"><label>파일 종류</label><select data-bt="format">'+['docx','pptx','xlsx','pdf'].map(function(f){ return '<option value="'+f+'"'+(d.format===f?' selected':'')+'>'+BD_FMT_LABEL[f]+'</option>'; }).join('')+'</select></div>'
        +'<div class="flapi-field"><label>상태</label><select data-bt="status"><option value="active"'+(d.status!=='off'?' selected':'')+'>사용</option><option value="off"'+(d.status==='off'?' selected':'')+'>중지</option></select></div></div>'
        +bdTplScopeHtml(d)
        +'<div class="flapi-hint">파일 없이 항목과 지침만으로 새 문서를 만드는 예전 방식(구조 참고)입니다. 새 템플릿은 양식 파일을 올려 등록합니다.</div>';
    } else if(tab==='form'){
      h+='<div class="flapi-sec">1. 항목 (문서 순서)</div>'
        +'<table class="flapi-tbl bd-sec-tbl"><thead><tr><th style="width:36px">#</th><th>항목 이름</th><th>힌트 (이 항목에 무엇을 쓸지)</th><th style="width:96px"></th></tr></thead><tbody>'
        +(d.sections||[]).map(function(s,i){ return '<tr><td style="color:var(--muted);padding:6px 10px">'+(i+1)+'</td><td><input type="text" maxlength="80" data-bt-sec="'+i+':title" value="'+esc(s.title||'')+'" placeholder="예: 핵심 성과"></td><td><input type="text" maxlength="200" data-bt-sec="'+i+':hint" value="'+esc(s.hint||'')+'" placeholder="예: 지난주 대비 증감을 수치로"></td><td class="x"><button type="button" data-bt-secup="'+i+'" aria-label="위로">▲</button><button type="button" data-bt-secdn="'+i+'" aria-label="아래로">▼</button><button type="button" data-bt-secdel="'+i+'" aria-label="삭제">✕</button></td></tr>'; }).join('')
        +'</tbody></table><button type="button" class="flapi-add" data-bt-secadd>+ 항목 추가</button>'
        +'<div class="flapi-sec">2. 입력 항목 (사용자가 주는 값)</div>'
        +'<table class="flapi-tbl"><thead><tr><th>이름</th><th>설명</th><th>예시</th><th>기본값</th><th style="width:60px">필수</th><th style="width:36px"></th></tr></thead><tbody>'
        +((d.inputs||[]).length?(d.inputs||[]).map(function(x,i){ return '<tr><td><input type="text" maxlength="40" data-bt-in="'+i+':name" value="'+esc(x.name||'')+'" placeholder="보고 기간"></td><td><input type="text" maxlength="200" data-bt-in="'+i+':description" value="'+esc(x.description||'')+'" placeholder="예: 9월 2주"></td><td><input type="text" maxlength="120" data-bt-in="'+i+':example" value="'+esc(x.example||'')+'"></td><td><input type="text" maxlength="120" data-bt-in="'+i+':default" value="'+esc(x['default']||'')+'" placeholder="비우면 필수"></td><td style="text-align:center"><input type="checkbox" data-bt-in="'+i+':required"'+(x.required!==false?' checked':'')+'></td><td class="x"><button type="button" data-bt-indel="'+i+'" aria-label="삭제">✕</button></td></tr>'; }).join(''):'<tr><td colspan="6" class="empty">비면 실행할 때 묻지 않습니다. 주제·기간처럼 매번 달라지는 값을 적어 두세요.</td></tr>')
        +'</tbody></table><button type="button" class="flapi-add" data-bt-inadd>+ 입력 항목 추가</button>'
        +'<div class="flapi-hint">비어 있는 필수 입력은 파일을 만들기 전에 질문 카드로 묻습니다. 기본값이 있으면 묻지 않습니다.</div>';
    } else if(tab==='guide'){
      var st=BD_STYLES[d.format]||BD_STYLES.docx, lo=d.format==='xlsx'?5:2, hi=d.format==='xlsx'?100:15;
      h+='<div class="flapi-field"><label>작성 지침 (최우선 규칙)</label><textarea data-bt="instruction" maxlength="2000" rows="6" placeholder="예: 결론 먼저, 수치는 표로, 존댓말 평서문, 3쪽 이내">'+esc(d.instruction||'')+'</textarea><div class="flapi-hint">기본 스타일 가이드와 충돌하면 이 지침이 이깁니다. 항목별 힌트는 양식 탭에 있습니다.</div></div>'
        +'<div class="flapi-row3"><div class="flapi-field"><label>자료 출처 기본값</label><select data-bt="source"><option value="context"'+(d.source==='context'?' selected':'')+'>대화 내용</option><option value="internal"'+(d.source==='internal'?' selected':'')+'>사내 자료 조회</option><option value="general"'+(d.source==='general'?' selected':'')+'>일반 지식</option></select></div>'
        +'<div class="flapi-field"><label>분량 ('+(d.format==='xlsx'?'행':'페이지')+', '+lo+'~'+hi+')</label><input type="number" min="'+lo+'" max="'+hi+'" data-bt="length" value="'+(+d.length||lo)+'"></div>'
        +'<div class="flapi-field"><label>스타일</label><select data-bt="style">'+st.map(function(s){ return '<option value="'+s[0]+'"'+(d.style===s[0]?' selected':'')+'>'+s[1]+'</option>'; }).join('')+'</select></div></div>';
    } else {
      h+='<div class="flapi-sec">AI에 전달되는 템플릿 지침</div><pre class="flapi-pre" style="white-space:pre-wrap">'+esc(bdTplPreviewText(d, true))+'</pre>'
        +'<div class="flapi-hint">구성원이 + 메뉴 › 템플릿 가져오기로 이 템플릿을 첨부하고 요청을 보내면, 비어 있는 필수 입력은 질문 카드로 받은 뒤 위 지침으로 파일을 만듭니다.</div>';
    }
    document.getElementById('bdTplBody').innerHTML=h;
    bdTranslate(bdTplOv);
  }
  /* 화면의 이름 칸(label)을 항목 이름으로 — 묶음 항목은 '묶음.이름' / the name box becomes the slot name ('group.name' inside a group) */
  function bdSlotName(s){
    var label=(s.label!==undefined?s.label:(s.group?s.name.slice(s.group.length+1):s.name)).replace(/\s+/g,' ').trim();
    return label?((s.group?s.group+'.':'')+label):s.name;
  }
  /* 끄기·이름 변경이 서버에 반영된 상태와 다르면 원본에서 표시본을 다시 만든다(/remark) → 새 파일 id. 아니면 그대로.
     When off/rename differ from what the server applied, re-derive the marked copy from the original (/remark) → a new file id. */
  function bdTplSync(){
    var form=BD.tpl, d=form&&form.draft;
    if(!d||!d.file||!d.file.auto) return Promise.resolve();
    var applied={}; ((d.file.analysis&&d.file.analysis.slots)||[]).forEach(function(s){ applied[s.key||s.name]={name:s.name, off:!!s.off}; });
    var off=[], rename={}, dirty=false;
    (d.slots||[]).forEach(function(s){
      var want=bdSlotName(s), was=applied[s.key]||{name:s.key, off:false};
      if(s.off) off.push(s.key); else if(want!==s.key) rename[s.key]=want;
      if(!!s.off!==was.off || (!s.off && want!==was.name)) dirty=true;
    });
    if(!dirty) return Promise.resolve();
    return bdFetch('/api/boards/template-files/'+encodeURIComponent(d.file_id)+'/remark', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({acting_user_id:bdActing(), off:off, rename:rename})}).then(function(r){
        if(BD.tpl!==form) return;
        var prev=d.slots.map(function(s){ var c={}; for(var k in s) c[k]=s[k]; c.name=bdSlotName(s); return c; });
        d.file=r.file; d.file_id=r.file.id; d.slots=bdSlotsFrom(r.file, {sections:[], inputs:[]}, prev);
      });
  }
  function bdTplSave(){
    var d=BD.tpl&&BD.tpl.draft; if(!d) return;
    if(BD.tpl.uploading){ say('파일을 다 읽은 뒤 저장해 주세요.'); return; }
    if(d.audience==='group'&&!(d.groups||[]).length){ say('적용 그룹을 하나 이상 선택해 주세요.'); return; }
    if(d.audience==='all') d.groups=[];
    if(!BD.tpl.legacy){
      if(!d.file_id){ say('양식 파일을 올려 주세요.'); return; }
      if(!(d.slots||[]).some(function(s){ return !s.off; })){ say('채울 항목을 하나 이상 남겨 주세요.'); return; }
    } else {
      d.sections=(d.sections||[]).filter(function(s){ return (s.title||'').trim(); });
      d.inputs=(d.inputs||[]).filter(function(x){ return (x.name||'').trim(); });
      if(!d.sections.length){ say('항목을 1개 이상 적어 주세요.'); BD.tpl.tab='form'; bdTplRender(); return; }
    }
    if(!(d.name||'').trim()){ say('템플릿 이름을 입력해 주세요.'); BD.tpl.tab='basic'; bdTplRender(); return; }
    var form=BD.tpl;
    (form.legacy?Promise.resolve():bdTplSync()).then(function(){
      if(BD.tpl!==form) return;
      var body=JSON.parse(JSON.stringify(d)); delete body.slots; delete body.audience; delete body.file;
      if(!form.legacy){
        var live=(d.slots||[]).filter(function(s){ return !s.off; });
        body.mode='fill'; body.format=d.file.format;
        body.sections=live.map(function(s){ return {title:s.name, hint:s.hint||''}; });
        body.inputs=live.filter(function(s){ return !s.group&&s.type!=='list'; }).map(function(s){ return {name:s.name, description:s.hint||'', example:s.example||'', 'default':s.def||'', required:!!s.required}; });
      }
      var url=form.id?'/api/boards/templates/'+encodeURIComponent(form.id):'/api/boards/templates', method=form.id?'PUT':'POST';
      return bdFetch(url, {method:method, headers:{'Content-Type':'application/json'}, body:JSON.stringify({acting_user_id:bdActing(), template:body})})
        .then(function(){ bdTplClose(); say('템플릿을 저장했습니다.'); bdLoad(); });
    }).catch(function(e){ say('저장 실패: '+(e.message||'')); if(BD.tpl===form) bdTplRender(); });
  }
  function bdTplUpload(file){
    if(!file||!BD.tpl) return;
    var form=BD.tpl, d=form.draft, owner=bdActing();
    if(d.audience==='group'&&!(d.groups||[]).length){ say('먼저 적용 그룹을 선택해 주세요.'); return; }
    var data=new FormData(); data.append('file',file); data.append('acting_user_id',owner); data.append('groups',JSON.stringify(d.groups||[]));
    form.uploading=true; bdTplRender();
    bdFetch('/api/boards/template-files',{method:'POST',body:data}).then(function(r){
      if(BD.tpl!==form||bdActing()!==owner) return;
      var prev=(d.slots||[]).map(function(s){ var c={}; for(var k in s) c[k]=s[k]; c.name=bdSlotName(s); return c; });
      d.file=r.file; d.file_id=r.file.id; d.format=r.file.format; d.mode='fill'; form.lastFile=r.file.auto?file:null;
      d.slots=bdSlotsFrom(r.file, {sections:[], inputs:[]}, prev);   // 파일을 바꿔도 이름이 같은 항목의 설명·필수·기본값은 유지 / same-named items keep their settings
      var a=r.analysis||{};
      if(!d.name) d.name=a.name||file.name.replace(/\.[^.]+$/,'');
      if(!d.description&&a.description) d.description=a.description;
      if(!d.instruction&&a.instruction) d.instruction=a.instruction;
      say(r.file.auto?'AI가 채울 자리를 찾았습니다. 항목을 확인해 주세요.':'양식의 표시를 읽었습니다. 항목을 확인해 주세요.');
    }).catch(function(e){say(e.message||'업로드에 실패했습니다.');}).finally(function(){form.uploading=false;if(BD.tpl===form)bdTplRender();});
  }
  function bdTplSample(){
    var form=BD.tpl, d=form&&form.draft; if(!d||!d.file_id) return;
    bdTplSync().then(function(){
      if(BD.tpl!==form) return;
      bdTplRender();
      return fetch('/api/boards/template-files/'+encodeURIComponent(d.file_id)+'/sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({acting_user_id:bdActing()})})
        .then(function(r){if(!r.ok)return r.json().then(function(j){throw new Error(j.detail||'샘플 생성 실패');});return r.blob();})
        .then(function(blob){var url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='sample.'+d.format;document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(url);},1000);});
    }).catch(function(e){say(e.message);});
  }
  function bdTplPut(t, patch, msg){
    var body=JSON.parse(JSON.stringify(t)); delete body.id; delete body.created; delete body.updated; delete body.version;
    Object.keys(patch||{}).forEach(function(k){ body[k]=patch[k]; });
    return bdFetch('/api/boards/templates/'+encodeURIComponent(t.id), {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({acting_user_id:bdActing(), template:body})})
      .then(function(){ if(msg) say(msg); bdLoad(); })
      .catch(function(e){ say('실패: '+(e.message||'')); });
  }

  /* ── 목록 동작 / list actions ── */
  function bdOnClick(e){
    var t, find=function(id){ return BD.templates.find(function(x){ return x.id===id; }); };
    if((t=e.target.closest('[data-bdtpledit]'))){ var te=find(t.dataset.bdtpledit); if(te) bdTplOpen(te); return; }
    if((t=e.target.closest('[data-bdtplcopy]'))){ var tc=find(t.dataset.bdtplcopy); if(!tc) return;
      var c=JSON.parse(JSON.stringify(tc)); c.name=(c.name||'')+' (복제)'; delete c.id; delete c.created; delete c.updated; delete c.version;
      bdFetch('/api/boards/templates', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({acting_user_id:bdActing(), template:c})})
        .then(function(){ say('템플릿을 복제했습니다.'); bdLoad(); }).catch(function(err){ say('복제 실패: '+(err.message||'')); });
      return; }
    if((t=e.target.closest('[data-bdtpltoggle]'))){ var tt=find(t.dataset.bdtpltoggle); if(tt) bdTplPut(tt, {status: tt.status==='active'?'off':'active'}, tt.status==='active'?'템플릿을 중지했습니다.':'템플릿을 다시 사용합니다.'); return; }
    if((t=e.target.closest('[data-bdtpldel]'))){ var td=find(t.dataset.bdtpldel); if(!td) return;
      if(!window.confirm("'"+td.name+"' 템플릿을 삭제할까요?")) return;
      bdFetch('/api/boards/templates/'+encodeURIComponent(td.id)+'?acting_user_id='+encodeURIComponent(bdActing()), {method:'DELETE'})
        .then(function(){ say('템플릿을 삭제했습니다.'); bdLoad(); }).catch(function(err){ say('삭제 실패: '+(err.message||'')); });
      return; }
  }

  /* 게시판 뷰(adapter.js)가 부른다: mount(목록을 그릴 요소) → 불러와 그린다, openNew() → 새 템플릿 패널, close() → 패널 닫기
     Called by the board view (adapter.js): mount(list element) loads and renders, openNew() opens the panel, close() closes it */
  window.AI365_boardAdmin={
    mount:function(el){ if(!el) return; BD.root=el; if(!el._bdBound){ el._bdBound=true; el.addEventListener('click', bdOnClick); } bdLoad(); },
    openNew:function(){ bdTplOpen(null); },
    close:function(){ bdTplClose(); BD.root=null; }
  };
})();
