/* Company templates: attach to the composer, then write the request. */
(function () {
  const E = ai365Esc, T = ai365T;
  const actor = () => window.AI365_ACTING_USER ? String(window.AI365_ACTING_USER.no) : '';
  const attachments = new Map();
  const key = place => actor() + ':' + (place === 'home' ? 'home' : String(currentChatId || 'home'));
  async function request(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : T('템플릿 요청을 처리하지 못했습니다.'));
    return data;
  }
  function config(t) {
    return {template_id: t.id, template_version: t.version, template_inputs: {}, format: t.format,
      topic: t.name, style: t.style, length: t.length, source: t.source || 'context'};
  }
  function paint() {
    ['home', 'chat'].forEach(place => {
      const input = document.getElementById(place + 'Input');
      if (!input) return;
      let box = document.getElementById('ai365TemplateChip-' + place);
      if (!box) {
        box = document.createElement('div'); box.id = 'ai365TemplateChip-' + place;
        // 컬렉션·파일 칩(.cmp-att)과 같이 입력창 아래에 둔다(2026-09-15 점검) / sits under the input like the collection chips
        box.className = 'ai365-template-chip'; input.parentNode.insertBefore(box, input.nextSibling);
      }
      const t = attachments.get(key(place)); box.hidden = !t;
      box.innerHTML = t ? '<span>' + E(t.name) + '</span><span class="ai365-tpl-badge">'
        + E(T((t.groups || []).length ? '그룹 전용' : '전체 공용')) + '</span>'
        + '<button type="button" aria-label="' + E(T('템플릿 제거')) + '">×</button>' : '';
      const remove = box.querySelector('button');
      if (remove) remove.onclick = () => { attachments.delete(key(place)); paint(); };
    });
  }
  const style = document.createElement('style');
  // 칩은 목업의 .cmp-chip.coll 규격(연보라 바탕·9px 라운드·12.5px), 질문 카드는 .form-card 머리글/본문/푸터 규격 / chip mirrors .cmp-chip.coll, the card uses the form-card head/body/foot
  style.textContent = '.ai365-template-chip{display:inline-flex;align-items:center;gap:6px;max-width:260px;margin:2px 6px 8px;padding:4px 5px 4px 10px;border:1px solid var(--primary-ring,#DCDFFA);border-radius:9px;color:var(--ink-2);background:var(--primary-soft,#EEF0FF);font-size:12.5px}'
    + '.ai365-template-chip[hidden]{display:none}.ai365-template-chip>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}'
    + '.ai365-template-chip button{display:flex;align-items:center;justify-content:center;border:0;background:none;color:var(--muted);cursor:pointer;font-size:16px;line-height:1;padding:2px 4px;border-radius:5px}'
    + '.ai365-template-chip button:hover{background:#E0E3EE;color:var(--ink-2)}'
    + '.ai365-template-question label{display:block;margin:10px 0 0;font-size:13px;font-weight:600;color:var(--ink-2)}'
    + '.ai365-template-question .form-input{display:block;width:100%;box-sizing:border-box;margin-top:6px}'
    + '.ai365-template-question .ai365-tq-lead{margin:0 0 4px;font-size:13px;color:var(--muted)}'
    + '.ai365-template-question .error{color:#B3261E;font-size:12px;margin:8px 0 0}.ai365-template-question .error:empty{display:none}';
  document.head.appendChild(style);
  window.AI365_templateAttach = function (t, anchor) {
    if (typeof ai365FlowAlive === 'function' && ai365FlowAlive()) { toast(T('워크플로우를 종료한 뒤 템플릿을 선택해 주세요.')); return; }
    const place = anchor && anchor.id === 'homeAttBtn' ? 'home'
      : (document.getElementById('viewChat')?.classList.contains('active') ? 'chat' : 'home');
    attachments.set(key(place), t); paint();
    document.getElementById(place + 'Input')?.focus();
  };
  window.AI365_templateTake = function (place) {
    const t = attachments.get(key(place));
    if (!t) return null;
    attachments.delete(key(place)); paint(); return config(t);
  };
  window.AI365_templateHandle = function (message) {
    const cfg = window.AI365_templateTake('chat');
    if (!cfg) return false;
    if (currentChatId && AI365_BACKEND_IDS.has(currentChatId)) ai365StreamReply(message, {docRun: cfg});
    else openBlankChat(message, {docRun: cfg});
    return true;
  };
  window.AI365_prepareTemplateMessage = async function (message, cfg, wrap, chatId, signal) {
    const owner = actor();
    const response = await request('/api/boards/templates/' + encodeURIComponent(cfg.template_id) + '/prepare-chat', {
      method: 'POST', signal, headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        acting_user_id: owner, chat_id: chatId, message, version: cfg.template_version || 0,
        inputs: cfg.template_inputs || {}, question_id: cfg.template_question_id || ''})});
    if (signal?.aborted || owner !== actor() || chatId !== currentChatId) return null;
    if (response.missing?.length) { window.AI365_templateQuestion(wrap, response, false, owner); return null; }
    return {message: response.message || message, cfg: {...cfg, ...response.docgen,
      template_inputs: response.inputs, template_version: response.template.version,
      template_question_id: response.question_id || '', template_prepared: true, saveUser: response.save_user}};
  };
  window.AI365_templateQuestion = function (wrap, card, answered, owner) {
    if (owner !== actor()) { wrap.textContent = T('이 템플릿 입력은 다른 사용자의 요청입니다.'); return; }
    wrap.innerHTML = '<div class="ai-body"><form class="form-card ai365-template-question" data-form="ai365-template">'
      + '<div class="form-card-head"><span class="form-card-title">' + E(T('템플릿 입력')) + ' · ' + E(card.name) + '</span></div>'
      + '<div class="form-body"><p class="ai365-tq-lead">' + E(T('작성에 필요한 정보를 입력해 주세요.')) + '</p>'
      + (card.missing || []).map((field, i) => '<label>' + E(field.name) + '<input class="form-input" data-template-field="' + E(field.name)
        + '" aria-label="' + E(field.name) + '" maxlength="120" required value="' + E(card.inputs?.[field.name] || '')
        + '" placeholder="' + E(field.example || field.description || '') + '"' + (answered ? ' disabled' : '') + '></label>').join('')
      + '<p class="error" role="alert"></p></div>'
      + '<div class="form-foot"><button type="submit" class="form-btn submit' + (answered ? '' : ' enabled') + '"' + (answered ? ' disabled' : '') + '>'
      + E(T(answered ? '입력 완료' : '작성하기')) + '</button></div></form></div>';
    const form = wrap.querySelector('form');
    const chatId = currentChatId;
    form.onsubmit = async event => {
      event.preventDefault();
      if (answered || owner !== actor() || chatId !== currentChatId || !form.reportValidity()) return;
      const inputs = {...card.inputs};
      form.querySelectorAll('[data-template-field]').forEach(input => { inputs[input.dataset.templateField] = input.value.trim(); });
      const button = form.querySelector('button'); button.disabled = true;
      try {
        const cfg = {template_id: card.template_id, template_version: card.version, template_inputs: inputs,
          template_question_id: card.question_id, format: card.format, topic: card.name};
        // A fresh wrapper preserves the question card and its retry inputs if validation fails.
        await ai365StreamReply(card.message, {docRun: cfg});
      } catch (err) { form.querySelector('.error').textContent = err.message; }
      finally { button.disabled = false; }
    };
  };
  const previousEffective = window.AI365_applyEffective;
  window.AI365_applyEffective = function () {
    attachments.clear(); paint();
    const menu = document.getElementById('cmpAttMenu');
    if (menu?.querySelector('[data-ai365-tplback]')) { menu.innerHTML = ''; menu.classList.remove('open'); }
    return previousEffective?.apply(this, arguments);
  };
  const previousOpen = openChat;
  openChat = function () { const result = previousOpen.apply(this, arguments); paint(); return result; };
  const previousView = showView;
  showView = function () { const result = previousView.apply(this, arguments); paint(); return result; };
  window.AI365_tplOpenForm = window.AI365_templateAttach;
  paint();
})();
