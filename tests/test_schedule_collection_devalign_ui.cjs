// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_schedule_collection_devalign_ui.cjs
// 예약 작업 페이지 · 컬렉션 화면의 Dev 원본 정렬(2026-10-28, outputs/design-diff/Dev_원본_정렬_명세.md 2.8 · 2.9): 위 60 머리 띠 · 제목 20 · 카드 hover ✎ ⋯ ·
// Dev 메뉴 순서 · 삭제 = Dev 모양 확인 창(window.confirm 없음) · 상세 머리 띠 없음, 컬렉션 표 머리 "생성일" · 행 56 · ⋯ 늘 보임 · ⋯ 메뉴의 고정 / 고정 해제 ·
// 대화 없는 상세의 Dev 빈 상태 · 오른쪽 칸 450 · 영어 왕복. 목업 전체 + 어댑터를 가짜 원점에 올린 격리 브라우저, 모든 요청은 메모리 스텁(서버 · DB 없음).
// Run with Playwright on NODE_PATH: node --test tests/test_schedule_collection_devalign_ui.cjs
// Dev-original alignment of the schedules page and the collection screens (2026-10-28, spec sections 2.8 and 2.9): the 60px head band,
// the 20px title, hover edit and ⋯ on cards, the Dev menu order, deletes in the Dev-shaped confirm (no window.confirm), no band on the
// detail; the collection head label "생성일", 56px rows, an always-visible ⋯, pin / unpin in the ⋯ menu, the Dev empty state of a detail
// without chats, the 450px side column and the English round trip. The whole mockup and adapter on a fake origin; every request is an
// in-memory stub (no server, no DB).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const kst = fs.readFileSync(path.join(__dirname, '../static/kst.js'), 'utf8');
const ORIGIN = 'http://sd.test';
const HTML = mockup.replace(/<head[^>]*>/i, m => m + '<script>' + kst + '</script>').replace('</body>', '<script src="/static/adapter.js"></script></body>');

function seedSchedules() {
  return [
    { id: 's1', name: '주간 매출 요약', message: '지난주 매출을 요약해줘', scope: '자동', status: 'active', rule: 'weekly', run_at: '09:00', days: [0],
      next_run_at: '2099-01-05T09:00:00', notify_email: true, agents: [], smf_files: [], scope_files: { knowledge_files: [], data_tables: [], data_bi: [], work: false } },
    { id: 's2', name: '재고 점검', message: '재고를 점검해줘', scope: '자동', status: 'paused', rule: 'daily', run_at: '17:30', days: [], notify_email: true,
      agents: [], smf_files: [], scope_files: { knowledge_files: [], data_tables: [], data_bi: [], work: false } },
    { id: 's3', name: '분기 보고', message: '분기 보고서를 써줘', scope: '자동', status: 'done', rule: 'once', run_at: '2026-09-05T09:00', days: [], notify_email: true,
      last_run_at: '2026-09-05T09:00:00', agents: [], smf_files: [], scope_files: { knowledge_files: [], data_tables: [], data_bi: [], work: false } },
  ];
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t) {
  const srv = { schedules: seedSchedules(), urls: [] };
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  t.after(() => page.close());
  const errors = [], dialogs = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => { dialogs.push(d.type()); d.dismiss(); });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method(), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (!p.startsWith('/api/')) return route.abort();
    srv.urls.push(method + ' ' + p);
    if (p === '/api/schedules' && method === 'GET') return json(srv.schedules);
    const runs = /^\/api\/schedules\/([^/]+)\/runs$/.exec(p);
    if (runs) return json([]);
    const one = /^\/api\/schedules\/([^/]+)$/.exec(p);
    if (one && method === 'DELETE') { srv.schedules = srv.schedules.filter(s => s.id !== one[1]); return json({ ok: true }); }
    if (one && method === 'PATCH') return json({ ok: true });
    if (p === '/api/collections' && method === 'GET') return json([]);   // 빈 응답 = 목업 시드 유지 / empty keeps the mockup seeds
    if (p.startsWith('/api/collections/')) return json({});
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    return json({ detail: 'stub' }, 404);
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.AI365_openSched === 'function' && typeof window.ai365DangerConfirm === 'function', null, { timeout: 10000 });
  return { page, errors, dialogs, srv };
}
async function until(fn) { for (let i = 0; i < 300 && !(await fn()); i++) await new Promise(r => setTimeout(r, 50)); assert.ok(await fn()); }
const texts = (page, sel) => page.$$eval(sel, es => es.map(e => e.textContent.trim()));
const css = (page, sel, props, pseudo) => page.$eval(sel, (el, a) => { const s = getComputedStyle(el, a[1] || null); return a[0].map(p => s.getPropertyValue(p)); }, [props, pseudo]);

test('schedules: the 60px band, the 20px title row, r8 cards with hover edit and ⋯, the Dev menus, and the detail without the band', async t => {
  const { page, errors } = await app(t);
  await page.click('#ai365SchedNav');
  await page.waitForSelector('#ai365SdInner .ai365-sd-item');
  assert.deepEqual(await page.$eval('#ai365SchedView .ai365-sd-top', el => [el.getBoundingClientRect().height, getComputedStyle(el).display]), [60, 'block']);
  assert.deepEqual(await css(page, '.ai365-sd-head h1', ['font-size', 'line-height', 'font-weight', 'color']), ['20px', '28px', '700', 'rgb(26, 29, 38)']);
  assert.deepEqual(await css(page, '.ai365-sd-sub', ['font-size', 'color', 'margin-bottom']), ['14px', 'rgb(93, 97, 106)', '32px']);
  assert.ok(await page.$eval('.ai365-sd-sub', el => el.previousElementSibling.classList.contains('ai365-sd-head')));   // 부제는 제목 줄 아래 / the subtitle sits below the title row
  assert.equal(await page.$eval('.ai365-sd-inner', el => el.getBoundingClientRect().width), 832);   // 768 + 좌우 32 / 768 plus 32 on each side
  assert.deepEqual(await css(page, '.ai365-sd-add', ['border-top-left-radius', 'font-size', 'font-weight']), ['9999px', '14px', '500']);
  assert.deepEqual(await css(page, '.ai365-sd-fbtn', ['border-top-color', 'border-top-left-radius']), ['rgb(220, 224, 235)', '9999px']);
  // 활성 필터: 카드 1장(r8 · #FAFBFE · 제목 14/500 · 라벨 12), ✎ · ⋯ 는 hover 에만 / the active filter: one card; edit and ⋯ only on hover
  assert.deepEqual(await texts(page, '.ai365-sd-item .ai365-sd-name'), ['주간 매출 요약']);
  assert.deepEqual(await css(page, '.ai365-sd-card', ['border-top-left-radius', 'background-color', 'padding-top', 'padding-left']), ['8px', 'rgb(250, 251, 254)', '12px', '16px']);
  assert.deepEqual(await css(page, '.ai365-sd-name', ['font-size', 'font-weight']), ['14px', '500']);
  assert.deepEqual(await css(page, '.ai365-sd-meta', ['font-size', 'color']), ['12px', 'rgb(139, 143, 163)']);
  assert.equal(await page.$eval('.ai365-sd-acts', el => getComputedStyle(el).opacity), '0');
  await page.hover('.ai365-sd-item');
  await until(async () => (await page.$eval('.ai365-sd-acts', el => getComputedStyle(el).opacity)) === '1');
  assert.ok(await page.$('.ai365-sd-item [data-sd-pen="s1"]'));
  await page.click('.ai365-sd-item [data-sd-menu="s1"]');
  assert.deepEqual(await texts(page, '.ai365-sd-kmenu .ai365-sd-fitem'), ['지금 실행', '일시정지', '삭제']);
  await page.keyboard.press('Escape');
  assert.equal(await page.$('.ai365-sd-kmenu'), null);
  // 일시정지 필터: 다시 시작(Dev 문구), 완료 필터: ✎ 없음 / paused shows Dev's 다시 시작, completed has no edit
  await page.click('[data-sd-fmenu]');
  assert.deepEqual(await texts(page, '.ai365-sd-fmenu .ai365-sd-fitem'), ['활성', '일시정지', '완료']);
  await page.click('[data-sd-filter="paused"]');
  await page.hover('.ai365-sd-item');
  await page.click('.ai365-sd-item [data-sd-menu="s2"]');
  assert.deepEqual(await texts(page, '.ai365-sd-kmenu .ai365-sd-fitem'), ['지금 실행', '다시 시작', '삭제']);
  await page.click('[data-sd-fmenu]');
  await page.click('[data-sd-filter="done"]');
  assert.equal(await page.$('.ai365-sd-item [data-sd-pen]'), null);
  // 상세: 머리 띠 없음 · ← 목록으로 14 · 정보 카드 #F2F6FF · ✎ · ⋯ 늘 보임 / the detail: no band, the back link, the #F2F6FF card, actions always shown
  await page.click('[data-sd-open="s3"]');
  await page.waitForSelector('.ai365-sd-dwrap');
  assert.equal(await page.$eval('#ai365SchedView .ai365-sd-top', el => getComputedStyle(el).display), 'none');
  assert.deepEqual(await css(page, '.ai365-sd-back button', ['font-size', 'color']), ['14px', 'rgb(93, 97, 106)']);
  assert.deepEqual(await css(page, '.ai365-sd-dwrap .ai365-sd-card', ['background-color']), ['rgb(242, 246, 255)']);
  assert.equal(await page.$eval('.ai365-sd-dwrap .ai365-sd-acts', el => getComputedStyle(el).opacity), '1');
  assert.deepEqual(await css(page, '.ai365-sd-sec-t', ['font-size', 'font-weight']), ['14px', '500']);
  await page.click('[data-sd-back]');
  await page.waitForSelector('#ai365SdInner .ai365-sd-head');
  assert.equal(await page.$eval('#ai365SchedView .ai365-sd-top', el => getComputedStyle(el).display), 'block');
  assert.deepEqual(errors, []);
});

test('schedules: delete opens the Dev-shaped confirm; cancel keeps it, delete sends DELETE, and no native dialog appears', async t => {
  const { page, errors, dialogs, srv } = await app(t);
  await page.click('#ai365SchedNav');
  await page.waitForSelector('#ai365SdInner .ai365-sd-item');
  await page.hover('.ai365-sd-item');
  await page.click('[data-sd-menu="s1"]');
  await page.click('[data-sd-act="delete"]');
  await page.waitForSelector('#ai365DcOv.show');
  assert.deepEqual([await page.textContent('#ai365DcOv .dialog-title'), await page.textContent('#ai365DcOv .dialog-body'), await texts(page, '#ai365DcOv .dialog-actions .btn')],
    ['삭제', '정말 이 예약 작업을 삭제하시겠습니까?', ['취소', '삭제']]);
  await page.click('#ai365DcOv .btn-ghost');
  await page.waitForSelector('#ai365DcOv:not(.show)', { state: 'attached' });
  assert.ok(!srv.urls.includes('DELETE /api/schedules/s1'));
  await page.hover('.ai365-sd-item');
  await page.click('[data-sd-menu="s1"]');
  await page.click('[data-sd-act="delete"]');
  await page.click('#ai365DcOv .btn-danger');
  await until(() => srv.urls.includes('DELETE /api/schedules/s1'));
  await until(async () => (await page.$$('.ai365-sd-item')).length === 0);
  assert.deepEqual(dialogs, []);
  assert.deepEqual(errors, []);
});

test('collections: Dev table head and rows, an always-visible ⋯ with pin / unpin, the Dev empty detail, the 450px side and the EN round trip', async t => {
  const { page, errors, srv } = await app(t);
  await page.evaluate(() => document.getElementById('collAddNav').click());
  await page.waitForSelector('#collBody .coll-row');
  assert.deepEqual(await page.$eval('#viewCollection .coll-head', el => [el.getBoundingClientRect().height, getComputedStyle(el.querySelector('.coll-title')).fontSize,
    getComputedStyle(el.querySelector('.coll-title')).fontWeight]), [60, '20px', '700']);
  assert.deepEqual(await css(page, '#collPageAdd', ['font-size', 'border-top-left-radius', 'padding-left']), ['16px', '9999px', '16px']);
  assert.deepEqual(await texts(page, '#collBody .coll-thead .coll-th'), ['제목', '내용', '생성일']);
  assert.deepEqual(await page.$eval('#collBody .coll-thead', el => [el.getBoundingClientRect().height, getComputedStyle(el).borderBottomColor]), [43, 'rgb(205, 209, 220)']);
  assert.deepEqual(await page.$eval('#collBody .coll-row', el => [el.getBoundingClientRect().height, getComputedStyle(el).borderBottomWidth]), [56, '0px']);
  assert.deepEqual(await css(page, '#collBody .coll-row-name', ['font-size', 'font-weight', 'color']), ['16px', '600', 'rgb(33, 36, 44)']);
  assert.deepEqual(await css(page, '#collBody .coll-row-time', ['font-size', 'color', 'text-align']), ['14px', 'rgb(159, 163, 173)', 'right']);
  assert.deepEqual(await page.$eval('#collBody .coll-row', el => [getComputedStyle(el.querySelector('.coll-row-more')).opacity, getComputedStyle(el.querySelector('.coll-row-pin')).display]), ['1', 'none']);
  // ⋯ 메뉴: 컬렉션 고정 · 수정 · 삭제(Dev 순서) → 고정하면 왼쪽 20 칸에 핀, 다시 열면 고정 해제 / pin, edit, delete; pinning shows the left pin and flips the item
  const row = await page.$eval('#collBody .coll-row', el => el.getAttribute('data-collrow'));
  await page.click('#collBody .coll-row[data-collrow="' + row + '"] [data-collmore]');
  await page.waitForSelector('#collMenu.show [data-ai365-collpin]');
  assert.deepEqual(await texts(page, '#collMenu .ctx-item'), ['컬렉션 고정', '수정', '삭제']);
  await page.click('#collMenu [data-ai365-collpin]');
  await until(async () => page.$eval('#collBody [data-collpin="' + row + '"]', b => b.classList.contains('pinned')));
  assert.ok(srv.urls.some(u => u.startsWith('PATCH /api/collections/')));
  assert.equal(await page.$eval('#collBody .coll-row[data-collrow="' + row + '"] .coll-row-tit', el => getComputedStyle(el, '::before').backgroundColor), 'rgb(68, 80, 206)');
  await page.click('#collBody .coll-row[data-collrow="' + row + '"] [data-collmore]');
  await page.waitForSelector('#collMenu.show [data-ai365-collpin]');
  assert.equal(await page.textContent('#collMenu [data-ai365-collpin]'), '고정 해제');
  await page.keyboard.press('Escape');
  // 대화 없는 컬렉션 상세: Dev 빈 상태 + 데모 시작 제안 칩, 머리 60 원 아이콘 · 제목 20 bold, 오른쪽 칸 450 / a detail without chats
  const empty = await page.$$eval('#collBody .coll-row', rs => { const r = rs.find(x => x.querySelector('.coll-row-name').textContent === '뉴스레터'); return r ? r.getAttribute('data-collrow') : null; });
  assert.ok(empty !== null);
  await page.click('#collBody .coll-row[data-collrow="' + empty + '"] .coll-row-name');
  await page.waitForSelector('#cdWork .ai365-cd-empty');
  assert.deepEqual(await texts(page, '#cdWork .ai365-cd-empty p'), ['나만의 컬렉션을 채워보세요!', '채팅을 시작하면 관련 대화가 이곳에 저장됩니다.']);
  assert.ok(await page.$('#cdWork .ai365-cd-empty + .cd-chips'));   // 시작 제안 칩(데모 전용)은 그 아래 / the demo starter chips below it
  assert.deepEqual(await page.$eval('#viewCollection .cd-top', el => el.getBoundingClientRect().height), 60);
  assert.deepEqual(await page.$eval('#viewCollection .cd-header-ic', el => [el.getBoundingClientRect().width, getComputedStyle(el).borderTopLeftRadius]), [60, '50%']);
  assert.deepEqual(await css(page, '#cdName', ['font-size', 'font-weight', 'color']), ['20px', '700', 'rgb(26, 28, 32)']);
  assert.equal(await page.$eval('#cdSide', el => el.getBoundingClientRect().width), 450);
  assert.deepEqual(await css(page, '#cdSide .cd-sec-t', ['font-size', 'font-weight']), ['20px', '600']);
  assert.deepEqual(await page.$eval('#cdSide .cd-add', el => [el.getBoundingClientRect().height, getComputedStyle(el).borderTopLeftRadius]), [46, '12px']);
  // 영어로 바꾸면 "Created on" · 빈 상태 EN, 한국어로 돌아오면 원문 / English labels, then the Korean originals again
  await page.click('#cdBack');
  await page.waitForSelector('#collListScreen:not([style*="none"]) .coll-row');
  await page.click('#ai365-lang-toggle');
  await until(async () => (await texts(page, '#collBody .coll-thead .coll-th'))[2] === 'Created on');
  await page.click('#ai365-lang-toggle');
  await until(async () => (await texts(page, '#collBody .coll-thead .coll-th')).join('|') === '제목|내용|생성일');
  assert.deepEqual(errors, []);
});

test('a fast EN to KO switch is not undone: the debounced re-translation re-checks the language inside its 40 ms timer', async t => {
  // 2026-10-28 수정 전에는 #viewCollection 관찰자가 40ms 뒤 언어를 다시 보지 않고 'en' 으로 번역해 KO 화면이 다시 영어가 됐다 /
  // before the 2026-10-28 fix the #viewCollection observer translated to 'en' 40 ms later without re-checking, turning the KO screen English again
  const { page, errors } = await app(t);
  await page.evaluate(() => document.getElementById('collAddNav').click());
  await page.waitForSelector('#collBody .coll-row');
  await page.evaluate(async () => {
    localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en');
    document.getElementById('collBody').appendChild(document.createElement('i'));
    await Promise.resolve();                                                       // 관찰자 콜백이 EN 일 때 돌아 40ms 타이머를 건다 / the observer runs while EN and arms its 40 ms timer
    await new Promise(r => setTimeout(r, 5));
    localStorage.setItem('ai365_lang', 'ko'); ai365ApplyLang('ko');                // 40ms 안에 KO 로 / back to KO within 40 ms
  });
  await page.waitForTimeout(150);
  assert.deepEqual(await texts(page, '#collBody .coll-thead .coll-th'), ['제목', '내용', '생성일']);
  assert.equal(await page.textContent('#collPageAdd'), '컬렉션 추가');
  assert.deepEqual(errors, []);
});

test('collections: the create dialog and the delete dialog take the Dev shapes', async t => {
  const { page, errors } = await app(t);
  await page.evaluate(() => document.getElementById('collAddNav').click());
  await page.waitForSelector('#collBody .coll-row');
  await page.click('#collPageAdd');
  await page.waitForSelector('#collFormOv.open');
  assert.equal(await page.$eval('#collFormOv .cd-modal', el => el.getBoundingClientRect().width), 600);
  assert.deepEqual(await css(page, '#collFormOv .cd-modal', ['border-top-left-radius', 'padding-top']), ['16px', '24px']);
  assert.deepEqual(await css(page, '#collFormOv .cd-modal-title', ['font-size', 'line-height', 'font-weight']), ['20px', '28px', '600']);
  assert.deepEqual(await texts(page, '#collFormOv .coll-field-opt'), ['(선택)', '(선택)']);
  assert.deepEqual(await css(page, '#collFormName', ['height', 'background-color', 'border-top-left-radius', 'font-size']), ['40px', 'rgb(246, 248, 253)', '8px', '16px']);
  assert.equal(await page.$eval('#collFormOv .coll-field:first-child .coll-field-l', el => getComputedStyle(el, '::after').content), '" *"');
  await page.click('#collFormX');
  // 삭제 창: 480 · [삭제] 하나(Dev) · 빨강 #CC2635 / the delete dialog: 480, one [Delete] as in Dev, red #CC2635
  await page.click('#collBody .coll-row [data-collmore]');
  await page.waitForSelector('#collMenu.show');
  await page.click('#collMenu [data-collmenu="delete"]');
  await page.waitForSelector('#collDelOv.open');
  assert.equal(await page.$eval('#collDelOv .cd-modal', el => el.getBoundingClientRect().width), 480);
  assert.deepEqual(await css(page, '#collDelConfirm', ['background-color', 'border-top-left-radius', 'font-size']), ['rgb(204, 38, 53)', '9999px', '16px']);
  await page.click('#collDelX');
  assert.deepEqual(errors, []);
});
