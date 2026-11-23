// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_billing_ui.cjs
// 관리 센터 › 청구 현황(2026-10-06 사용자 시안 개편 · 같은 날 Ai365 Manage 인보이스와 숫자 맞춤) — 청구 월 필터 · 요약 카드 · 탭 3개
// (금액 구성 | AI 사용량 | 월별 청구 내역) · 청구서 보기(한/영 · 인쇄). 숫자는 Manage 엠클라우드브리지(CUST-0001) 인보이스 12개월(2025-10 ~ 2026-09)과 같고
// (두 시드를 생성기 하나로 같이 만들었다), 고객 화면이라 원가 · 가산율은 나오지 않는다. 네트워크는 전부 스텁이다.
// Run with Playwright on NODE_PATH: node --test tests/test_billing_ui.cjs
// Admin Center › Billing (rebuilt from the user's mockups 2026-10-06 and aligned with Ai365 Manage the same day): the billing-month filter, the
// summary card, three tabs and the invoice viewer (Korean/English, print). The numbers equal Manage's CUST-0001 invoices for Oct 2025 - Sep 2026
// (both seeds come from one generator); as a customer view it never shows cost or the markup rate. Every network call is stubbed.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const ORIGIN = 'http://bl.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  t.after(() => page.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname;
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [], knowledge: [] });
    if (p.startsWith('/api/')) return json({ detail: 'stub' }, 404);
    return route.abort();
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.ai365ApplyLang === 'function' && !!document.getElementById('navPerm'));
  await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="billing"]').click(); });
  await page.waitForSelector('#blSum .bl-sum-v');
  return { page, errors };
}
const txt = (page, sel) => page.$eval(sel, e => e.textContent.trim());
const txts = (page, sel) => page.$$eval(sel, es => es.map(e => e.textContent.trim()));
const cells = (page, sel) => page.$$eval(sel, trs => trs.map(tr => [...tr.cells].map(c => c.textContent.trim()).join('|')));
const num = s => +String(s).replace(/[^\d]/g, '');

test('the monthly invoices keep Manage\'s arithmetic, numbering and paid flags, and carry no cost or markup', () => {
  const start = mockup.indexOf('  var BL_DATA=['), end = mockup.indexOf('\n  ];', start);
  assert.ok(start > 0 && end > start);
  const plain = v => JSON.parse(JSON.stringify(v));   // vm 영역 값을 이 영역 값으로 / plain values out of the vm realm
  const data = plain(vm.runInNewContext('[' + mockup.slice(mockup.indexOf('[', start) + 1, end) + ']'));
  const fixed = plain(vm.runInNewContext('(' + mockup.slice(mockup.indexOf('[', mockup.indexOf('  var BL_FIXED=[')), mockup.indexOf('\n  ];', mockup.indexOf('  var BL_FIXED=[')) + 4) + ')'));
  assert.equal(data.length, 12);
  assert.deepEqual(fixed.map(f => f[0] + ':' + f[5]), ['core:1000000', 'groupware:0', 'knowledge:1000000', 'data:1000000', 'custom:1000000']);
  data.forEach((r, i) => {
    const ym = r.y + '-' + String(r.m).padStart(2, '0'), d = new Date(2025, 9 + i, 1);
    assert.equal(ym, d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'));
    assert.equal(r.no, 'INV-' + ym + '-' + String(42 + i * 10).padStart(4, '0'));   // Manage 번호 / Manage's numbering
    assert.equal(r.paid, i < 11 ? 1 : 0);                                              // 마지막 달만 미납 / only the latest month is unpaid
    assert.equal(r.tok.length, 13);
    const subtotal = 4000000 + r.tok.reduce((a, t) => a + t[2], 0) + r.search + r.storage + r.web[1];
    assert.ok(r.cut >= 0 && r.cut < 10, ym);
    assert.equal(subtotal, r.supply, ym);                                              // 공급가액 = 항목 합 / supply = the items
    assert.equal(r.vat, Math.floor(r.supply * 0.1), ym);
    assert.equal((r.supply + r.vat) % 10, r.cut, ym);                                   // 절사는 부가세 포함 합계에서 / the cut comes off supply + VAT
    assert.equal(r.total, r.supply + r.vat - r.cut, ym);
    assert.equal(r.total % 10, 0, ym);
    assert.equal(r.web[1], Math.round(r.web[0] * 11.2), ym);                          // Tavily 크레딧당 $0.008 × 1,400원 / per credit
    assert.deepEqual(Object.keys(r).sort(), ['cut', 'm', 'no', 'paid', 'search', 'storage', 'supply', 'tok', 'total', 'vat', 'web', 'y'], ym);
  });
});

test('September shows the latest invoice: filter, summary card and the amount breakdown without cost or markup', async t => {
  const { page, errors } = await app(t);
  assert.equal(await page.$eval('#blYear', e => e.value), '2026');
  assert.equal(await page.$eval('#blMonth', e => e.value), '9');
  assert.equal(await txt(page, '#blSub'), '월별 사용량에 따른 청구 금액과 확정 인보이스, 금액 구성 및 AI 사용량 내역을 확인합니다.');
  assert.equal(await txt(page, '#blTotal'), '6,085,780원');
  assert.deepEqual(await txts(page, '#blSum .bl-legend .bl-lg'), ['정액 4,000,000원', 'AI 토큰 1,372,974원', 'Azure AI Search 104,000원', '스토리지 40,100원', '웹 검색 15,456원', '부가세 553,253원']);
  assert.equal(await txt(page, '#blSum .bl-sum-meta'), 'INV-2026-09-0152 발행 · 납기 2026. 10. 31. · 미납');
  assert.deepEqual(await page.$$eval('#blSum .bl-mini', ms => ms.map(m => m.querySelector('.bl-mini-v').textContent + '|' + m.querySelector('.bl-dl').textContent)),
    ['+126,990원|▲ 2.1%', '228,583,896토큰|▲ 6.3%', '40,100원|▲ 7.8%']);
  assert.deepEqual(await txts(page, '#blTabs .bl-tab'), ['금액 구성', 'AI 사용량', '월별 청구 내역']);
  assert.equal(await txt(page, '#blTabs .bl-tab.on'), '금액 구성');
  assert.equal(await txt(page, '#blPane .bl-card-tt'), '2026년 9월 요금 항목별 산정 내역');
  assert.deepEqual(await cells(page, '#blPane tbody tr'), [
    '정액 항목',
    '기본 플랫폼 사용료|정액|1개월 × 1,000,000원|1,000,000원|18.1%',
    '모듈 서비스이용료· 에이전트 4종 · 기본 포함 1종',
    '그룹웨어 에이전트 (기본)|정액|플랫폼 기본 포함 · 별도 과금 없음|0원|0.0%',
    '지식관리 에이전트|정액|1개월 × 1,000,000원|1,000,000원|18.1%',
    '데이터분석 에이전트|정액|1개월 × 1,000,000원|1,000,000원|18.1%',
    '업무자동화 에이전트|정액|1개월 × 1,000,000원|1,000,000원|18.1%',
    '정액 소계|||4,000,000원|72.3%',
    '사용량 항목',
    'AI 토큰 사용료 · Claude|사용량|입력 46,592,984 · 출력 10,577,630 토큰|473,140원|8.5%',
    'AI 토큰 사용료 · Gemini|사용량|입력 51,971,619 · 출력 13,430,148 토큰|155,315원|2.8%',
    'AI 토큰 사용료 · GPT|사용량|입력 89,043,062 · 출력 16,968,453 토큰|744,519원|13.4%',
    'Azure AI Search 사용료|사용량|Azure 청구 금액 그대로|104,000원|1.9%',
    '스토리지 사용 비용 (Blob Storage)|사용량|Azure 청구 금액 그대로|40,100원|0.7%',
    '웹 검색 사용료 (Tavily)|사용량|1,380 크레딧|15,456원|0.3%',
    '사용량 소계|||1,532,530원|27.7%',
    '사용료 합계 (공급가액)|||5,532,530원|100%',
    '부가세 10%|||553,253원|',
    '10원 미만 절사|||−3원|',
    '청구 금액|||6,085,780원|']);
  // 고객 화면: 원가 · 가산율 · 마진은 어디에도 없다 / a customer view: no cost, markup or margin anywhere
  for (const tab of ['amount', 'ai', 'monthly']) {
    await page.click('[data-bltab="' + tab + '"]');
    assert.equal(await page.$eval('#pgBillingScroll', e => /원가|가산|마진/.test(e.innerText)), false, tab);
  }
  assert.deepEqual(errors, []);
});

test('AI usage lists our models with their charges and the monthly history adds up with paid flags', async t => {
  const { page, errors } = await app(t);
  await page.click('[data-bltab="ai"]');
  assert.equal(await txt(page, '#blTabs .bl-tab.on'), 'AI 사용량');
  assert.equal(await txt(page, '#blPane .bl-card-aux'), '2026년 9월 · AI 토큰 사용료 기준 구성비');
  assert.deepEqual(await txts(page, '#blPane .bl-mlegend .bl-lg'), ['Claude 34.5% · 57,170,614 토큰', 'Gemini 11.3% · 65,401,767 토큰', 'GPT 54.2% · 106,011,515 토큰']);
  const ai = await cells(page, '#blPane .bl-tbl tbody tr');
  assert.deepEqual(ai.filter(r => r.includes('|')).map(r => r.split('|')[0]), ['Claude Haiku 4.5', 'Claude Sonnet 5', 'Claude Opus 4.8', 'Claude Opus 5', 'Claude Fable 5', 'Claude 소계',
    'Gemini 3.8 Flash', 'Gemini 3.7 Flash', 'Gemini 3.5 Flash-Lite', 'Gemini 소계', 'GPT-6 Astra', 'GPT-5.6 Sol', 'GPT-5.6 Terra', 'GPT-5.6 Luna', 'text-embedding-3-large', 'GPT 소계', '합계']);
  assert.ok(ai.includes('Claude Sonnet 5|22,640,811|5,027,702|180,606원|13.2%'));
  assert.ok(ai.includes('GPT-5.6 Terra|34,180,564|8,059,203|311,986원|22.7%'));
  assert.ok(ai.includes('text-embedding-3-large|6,830,480|0|1,678원|0.1%'));
  assert.equal(ai.at(-1), '합계|187,607,665|40,976,231|1,372,974원|100%');
  // 월별 청구 내역 / monthly history
  await page.click('[data-bltab="monthly"]');
  const rows = await cells(page, '#blPane .bl-mtbl tbody tr');
  assert.equal(rows.length, 12);
  assert.equal(rows[0], '2026년 9월|4,000,000|1,372,974|104,000|40,100|15,456|5,532,530|553,253|6,085,780|미납|청구서 보기');
  assert.equal(rows[1], '2026년 8월|4,000,000|1,261,380|104,000|37,200|14,504|5,417,084|541,708|5,958,790|납부 완료|청구서 보기');
  assert.equal(rows[11].split('|')[0], '2025년 10월');
  assert.deepEqual(rows.map(r => r.split('|')[9]), ['미납'].concat(Array(11).fill('납부 완료')));
  const foot = (await cells(page, '#blPane .bl-mtbl tfoot tr'))[0].split('|');
  assert.equal(foot[0], '확정 12개월 합계');
  const col = k => rows.reduce((a, r) => a + num(r.split('|')[k]), 0);
  for (const k of [1, 2, 3, 4, 5, 6, 7, 8]) assert.equal(num(foot[k]), col(k), 'column ' + k);
  for (const r of rows) {   // 항목 합 = 공급가액, 공급가액 + 부가세 − 절사(10원 미만) = 합계 / the items make the supply; supply + VAT minus the cut = total
    const c = r.split('|').slice(1, 9).map(num), cut = c[5] + c[6] - c[7];
    assert.equal(c[0] + c[1] + c[2] + c[3] + c[4], c[5], r); assert.ok(cut >= 0 && cut < 10 && c[7] % 10 === 0, r);
  }
  assert.equal(await txt(page, '#blPane .bl-note'), '청구 합계는 공급가액과 부가세를 더한 뒤 10원 미만을 절사한 금액입니다.');
  assert.deepEqual(await page.$$eval('#blPane .bl-svg text', ts => ts.filter(t => /월$|만$/.test(t.textContent)).map(t => t.textContent)).then(v => [v.length, v.includes('553만')]), [13, true]);
  assert.equal(await page.$eval('#blPane .bl-tbl-wrap', e => e.scrollWidth - e.clientWidth), 0);   // 1440px 에서 표가 넘치지 않는다 / no table overflow at 1440px
  assert.deepEqual(errors, []);
});

test('the invoice viewer shows the Manage document lines, closes with Escape and prints only the invoice', async t => {
  const { page, errors } = await app(t);
  await page.evaluate(() => { window.__printed = 0; window.print = () => { window.__printed++; }; });
  await page.click('[data-bltab="monthly"]');
  await page.click('#blPane .bl-mtbl tbody tr:first-child [data-blinv]');
  await page.waitForSelector('#blInvOv .bl-doc');
  assert.equal(await txt(page, '#blInvTt'), '청구서 보기');
  assert.equal(await txt(page, '#blInvOv .bl-inv-head p'), 'INV-2026-09-0152 · 2026년 9월 청구분');
  assert.equal(await txt(page, '#blInvOv .bl-doc-tt'), '청 구 서');
  assert.match(await txt(page, '#blInvOv .bl-doc-no'), /^INV-2026-09-0152발행일 2026\. 10\. 1\.납기일 2026\. 10\. 31\.$/);
  assert.match(await txt(page, '#blInvOv .bl-party:first-child'), /^공급자엠클라우드브리지사업자등록번호 128-81-00000대표자 이혁재서울특별시 강남구 테헤란로 123, 12층$/);
  assert.match(await txt(page, '#blInvOv .bl-party:last-child'), /^공급받는자엠클라우드브리지사업자등록번호 214-87-60123담당 경영지원팀 \/ 매니저 정하은haeun\.jung@mcloudbridge\.com$/);
  assert.equal(await txt(page, '#blInvOv .bl-doc-meta'), '청구 기간 2026년 9월 1일 ~ 30일결제 조건 익월 말일결제 상태 미납');
  assert.deepEqual(await cells(page, '#blInvOv .bl-doc-tbl tbody tr'), ['정액 항목', '기본 플랫폼 사용료|1|개월|1,000,000|1,000,000', '모듈 서비스이용료 · 그룹웨어 에이전트 (기본)|1|개월|0|0',
    '모듈 서비스이용료 · 지식관리 에이전트|1|개월|1,000,000|1,000,000', '모듈 서비스이용료 · 데이터분석 에이전트|1|개월|1,000,000|1,000,000',
    '모듈 서비스이용료 · 업무자동화 에이전트|1|개월|1,000,000|1,000,000', '사용량 항목',
    'AI 토큰 사용료 · Claude (57,170,614 토큰)|1|식|473,140|473,140', 'AI 토큰 사용료 · Gemini (65,401,767 토큰)|1|식|155,315|155,315', 'AI 토큰 사용료 · GPT (106,011,515 토큰)|1|식|744,519|744,519',
    'Azure AI Search 사용료|1|식|104,000|104,000', '스토리지 사용 비용 (Blob Storage)|1|식|40,100|40,100', '웹 검색 사용료 (Tavily · 1,380 크레딧)|1|식|15,456|15,456']);
  assert.deepEqual(await txts(page, '#blInvOv .bl-doc-sum div'), ['정액 소계4,000,000원', '사용량 소계1,532,530원', '공급가액5,532,530원', '부가세 (10%)553,253원', '절사 (10원 단위)− 3원', '청구 합계6,085,780원']);
  assert.match(await txt(page, '#blInvOv .bl-doc-bank'), /^입금 계좌 엠클라우드브리지 · 기업은행 000000-00-000000\|납기일까지/);
  assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-blpdf')), true);
  await page.click('[data-blpdf]');
  assert.equal(await page.evaluate(() => window.__printed), 1);
  assert.equal(await page.evaluate(() => document.body.classList.contains('bl-printing')), true);
  await page.emulateMedia({ media: 'print' });
  assert.deepEqual(await page.evaluate(() => [...document.body.children].filter(e => e.id !== 'blInvOv' && getComputedStyle(e).display !== 'none').map(e => e.tagName + '#' + e.id)), []);
  assert.equal(await page.$eval('#blInvOv .bl-inv-foot', e => getComputedStyle(e).display), 'none');
  await page.emulateMedia({ media: 'screen' });
  await page.click('[data-blmail]');
  assert.match(await txt(page, '#toast, .toast'), /청구서를 이메일로 보냈습니다 · haeun\.jung@mcloudbridge\.com/);
  await page.keyboard.press('Escape');
  assert.equal(await page.$('#blInvOv'), null);
  assert.equal(await page.evaluate(() => document.body.classList.contains('bl-printing')), false);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.blinv), '11');   // 연 단추로 포커스가 돌아온다 / focus returns to the opener
  assert.deepEqual(errors, []);
});

test('month links, the query and downloads follow the selected month', async t => {
  const { page, errors } = await app(t);
  await page.click('[data-bltab="monthly"]');
  await page.click('#blPane .bl-mtbl tbody tr:nth-child(2) [data-blmon]');   // 2026년 8월 / August
  assert.equal(await txt(page, '#blTabs .bl-tab.on'), '금액 구성');
  assert.equal(await txt(page, '#blTotal'), '5,958,790원');
  assert.equal(await page.$eval('#blMonth', e => e.value), '8');
  assert.equal(await txt(page, '#blSum .bl-sum-meta'), 'INV-2026-08-0142 발행 · 납기 2026. 9. 30. · 납부 완료');
  // 데이터 없는 달 → 안내, 첫 달 → 전월 자료 없음 / a month without data, then the first month
  await page.selectOption('#blYear', '2025');
  await page.selectOption('#blMonth', '1');
  await page.click('#blQuery');
  assert.match(await txt(page, '#toast, .toast'), /해당 월의 청구 데이터가 없습니다/);
  assert.equal(await page.$eval('#blYear', e => e.value), '2026');
  await page.selectOption('#blYear', '2025');
  await page.selectOption('#blMonth', '10');
  await page.click('#blQuery');
  assert.equal(await txt(page, '#blTotal'), '4,791,250원');
  assert.equal(await txt(page, '#blSum .bl-sum-meta'), 'INV-2025-10-0042 발행 · 납기 2025. 11. 30. · 납부 완료');
  assert.deepEqual(await txts(page, '#blSum .bl-dl'), ['전월 자료 없음', '전월 자료 없음', '전월 자료 없음']);
  assert.ok(!(await cells(page, '#blPane tbody tr')).some(r => r.startsWith('10원 미만 절사')));   // 이 달은 절사액 0원 = 절사 줄 없음 / no cut this month, so no cut row
  // 내려받기 / downloads
  const [d1] = await Promise.all([page.waitForEvent('download'), page.click('[data-bldl="amount"]')]);
  assert.equal(d1.suggestedFilename(), '청구현황_금액구성_2025-10.csv');
  const amount = fs.readFileSync(await d1.path(), 'utf8');
  assert.equal(amount.charCodeAt(0), 0xFEFF);
  assert.match(amount, /\r\n부가세 10%,,,435568,\r\n청구 금액,,,4791250,\r?$/);   // 이 달은 절사액 0원 = 절사 줄 없음 / no cut this month
  const [d2] = await Promise.all([page.waitForEvent('download'), page.click('#blExport')]);
  assert.equal(d2.suggestedFilename(), '청구현황_월별내역_2025-10_2026-09.csv');
  const hist = fs.readFileSync(await d2.path(), 'utf8').slice(1).split('\r\n');
  assert.equal(hist.length, 14);
  assert.equal(hist[0], '청구 월,정액,AI 토큰,Azure AI Search,스토리지,웹 검색,공급가액,부가세,청구 합계,납부,인보이스');
  assert.equal(hist[1], '2026년 9월,4000000,1372974,104000,40100,15456,5532530,553253,6085780,미납,INV-2026-09-0152');
  assert.equal(hist[4], '2026년 6월,4000000,1381983,104000,31500,18603,5536086,553608,6089690,납부 완료,INV-2026-06-0122');
  await page.click('[data-bltab="ai"]');
  const [d3] = await Promise.all([page.waitForEvent('download'), page.click('[data-bldl="ai"]')]);
  assert.equal(d3.suggestedFilename(), '청구현황_AI사용량_2025-10.csv');
  assert.deepEqual(errors, []);
});

test('English: the page and the invoice read in English with no Korean left', async t => {
  const { page, errors } = await app(t);
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await page.waitForFunction(() => document.getElementById('blQuery').textContent === 'Search');
  assert.equal(await txt(page, '#blTotal'), '₩6,085,780');
  assert.deepEqual(await txts(page, '#blTabs .bl-tab'), ['Amount breakdown', 'AI usage', 'Monthly billing history']);
  assert.equal(await txt(page, '#blPane .bl-card-tt'), 'Charges by item, September 2026');
  const hangul = sel => page.$eval(sel, e => (e.innerText.match(/[가-힣]+/g) || []).join(' '));
  assert.equal(await hangul('#pgBillingScroll'), '');
  for (const tab of ['ai', 'monthly']) { await page.click('[data-bltab="' + tab + '"]'); assert.equal(await hangul('#pgBillingScroll'), '', tab); }
  assert.equal(await page.$eval('#blPane .bl-tbl-wrap', e => e.scrollWidth - e.clientWidth), 0);
  await page.click('#blPane .bl-mtbl tbody tr:first-child [data-blinv]');
  await page.waitForSelector('#blInvOv .bl-doc');
  assert.equal(await txt(page, '#blInvTt'), 'View Invoice');
  assert.equal(await txt(page, '#blInvOv .bl-inv-head p'), 'INV-2026-09-0152 · September 2026 Billing');
  assert.equal(await txt(page, '#blInvOv .bl-doc-tt'), 'INVOICE');
  assert.equal(await txt(page, '#blInvOv .bl-doc-meta'), 'Billing Period Sep 1 – 30, 2026Payment Terms End of next monthPayment Status Unpaid');
  assert.deepEqual(await txts(page, '#blInvOv .bl-doc-sum div'), ['Fixed Subtotal₩4,000,000', 'Usage Subtotal₩1,532,530', 'Supply Amount₩5,532,530', 'VAT (10%)₩553,253', 'Rounding (₩10 units)− ₩3', 'Total Due₩6,085,780']);
  assert.ok((await cells(page, '#blInvOv .bl-doc-tbl tbody tr')).includes('Web Search Usage Fee (Tavily · 1,380 credits)|1|Lot|15,456|15,456'));
  assert.match(await txt(page, '#blInvOv .bl-party:first-child'), /MCloudBridge.*CEO Lee Hyuk-jae/);
  assert.deepEqual(await txts(page, '#blInvOv .bl-inv-foot button'), ['Send Email', 'Save as PDF']);
  assert.equal(await hangul('#blInvOv'), '');
  // 창을 연 채 한국어로 → 창도 바뀐다 / switching back to Korean redraws the open invoice too
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'ko'); ai365ApplyLang('ko'); });
  await page.waitForFunction(() => document.getElementById('blInvTt').textContent === '청구서 보기');
  assert.deepEqual(errors, []);
});

// 2026-10-07 사용자 지시: 영어 제목 'Billing status', 요약 작은 카드 글자가 카드 밖으로 넘치지 않게(좁으면 증감 줄바꿈, 1536px 이상은 520px 한 줄;
// 100명 규모의 9자리 토큰 합계는 Total tokens 카드만 줄바꿈 허용)
// User requests 2026-10-07: the English title reads 'Billing status' and no summary-card text spills out of its card
// (the change label wraps when narrow; from 1536px the cards get 520px and stay on one line, except the 9-digit Total tokens card)
test('English: the title reads Billing status and no summary card spills in any month; from 1536px value and change share one line (Total tokens may wrap)', async t => {
  const { page, errors } = await app(t);
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await page.waitForFunction(() => document.getElementById('blQuery').textContent === 'Search');
  assert.equal(await txt(page, '#pgBillingScroll .pg-pagetitle'), 'Billing status');
  assert.equal(await txt(page, '#pgBillingScroll .pg-breadcrumb span:last-child'), 'Billing status');
  const yms = [[2025, 10], [2025, 11], [2025, 12]].concat([1, 2, 3, 4, 5, 6, 7, 8, 9].map(m => [2026, m]));
  const spill = [], wrapped = [];
  for (const w of [1280, 1440, 1600]) {
    await page.setViewportSize({ width: w, height: 1000 });
    for (const [y, m] of yms) {
      await page.selectOption('#blYear', String(y)); await page.selectOption('#blMonth', String(m)); await page.click('#blQuery');
      const cards = await page.$$eval('#blSum .bl-mini', ms => ms.map(el => {
        const inner = el.getBoundingClientRect().right - parseFloat(getComputedStyle(el).paddingRight);
        const kids = [...el.querySelectorAll('.bl-mini-row > *')].map(k => k.getBoundingClientRect());
        return { lb: el.querySelector('.bl-mini-lb').textContent, over: Math.round(Math.max(...kids.map(r => r.right)) - inner),
          two: kids.length > 1 && Math.abs(kids[kids.length - 1].bottom - kids[0].bottom) > 8 };
      }));
      for (const c of cards) {
        if (c.over > 0) spill.push(`${w}px ${y}-${m} ${c.lb} +${c.over}px`);
        if (c.two && w >= 1536 && c.lb !== 'Total tokens') wrapped.push(`${w}px ${y}-${m} ${c.lb}`);   // 9자리 토큰 합계(100명 규모)는 줄바꿈 허용 / 9-digit token totals may wrap
      }
    }
  }
  assert.deepEqual(spill, []);
  assert.deepEqual(wrapped, []);
  assert.equal(await page.$eval('#blSum', e => getComputedStyle(e).gridTemplateColumns.split(' ')[1]), '520px');   // 1600px
  await page.evaluate(() => document.getElementById('navPerm').click());
  await page.waitForSelector('#pgHubScroll .hub-card');
  assert.equal(await txt(page, '[data-hubcard="billing"] .hub-card-tt'), 'Billing status');
  assert.deepEqual(errors, []);
});

// 2026-10-07 사용자 지시: 요약 카드 범례가 옆 칸으로 넘치지 않게 — 공간이 되면 3칸, 좁으면 2칸 · 1칸(사이드바가 있는 1366px 이하)
// User request 2026-10-07: the summary legend never spills into the next column (three columns when there is room, fewer when narrow)
test('the summary legend never spills into the next column: three columns from 1440px, fewer when narrow, in Korean and English', async t => {
  const { page, errors } = await app(t);
  const yms = [[2025, 10], [2025, 11], [2025, 12]].concat([1, 2, 3, 4, 5, 6, 7, 8, 9].map(m => [2026, m]));
  const spill = [], cols = {};
  for (const lang of ['ko', 'en']) {
    await page.evaluate(l => { localStorage.setItem('ai365_lang', l); ai365ApplyLang(l); }, lang);
    await page.waitForFunction(l => document.getElementById('blQuery').textContent === (l === 'en' ? 'Search' : '조회'), lang);
    for (const w of [1180, 1280, 1366, 1440, 1920]) {
      await page.setViewportSize({ width: w, height: 1000 });
      for (const [y, m] of yms) {
        await page.selectOption('#blYear', String(y)); await page.selectOption('#blMonth', String(m)); await page.click('#blQuery');
        const r = await page.$eval('#blSum .bl-legend', lg => ({
          cols: getComputedStyle(lg).gridTemplateColumns.split(' ').length,
          over: [...lg.querySelectorAll('.bl-lg')].map(e => { const rg = document.createRange(); rg.selectNodeContents(e); return [e.textContent, Math.round(rg.getBoundingClientRect().right - e.getBoundingClientRect().right)]; }).filter(x => x[1] > 0),
        }));
        r.over.forEach(([text, px]) => spill.push(`${lang} ${w}px ${y}-${m} ${text} +${px}px`));
        cols[lang + ' ' + w] = r.cols;
      }
    }
  }
  assert.deepEqual(spill, []);
  assert.deepEqual(cols, { 'ko 1180': 1, 'ko 1280': 2, 'ko 1366': 2, 'ko 1440': 3, 'ko 1920': 3, 'en 1180': 1, 'en 1280': 2, 'en 1366': 2, 'en 1440': 3, 'en 1920': 3 });
  assert.deepEqual(errors, []);
});
