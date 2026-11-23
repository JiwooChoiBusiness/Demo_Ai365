// 한국 시간(KST) 화면 도우미(static/kst.js)와 그것을 쓰는 화면 함수: 브라우저가 뉴욕 시간대여도 KST 로 계산하고 표시하는지 본다.
// 네트워크는 전부 막는다. 목업·교육·홈·이메일 화면의 실제 코드 조각을 뉴욕 시간대 페이지에 올리고, "지금"이 필요한 검사는 시계를
// 2026-10-05T16:00:00Z(= KST 10월 6일 01:00 화요일, 뉴욕 10월 5일 12:00, UTC 10월 5일)로 고정한다. 세 달력의 날짜가 갈리는
// 순간이라 브라우저 로컬이나 UTC 로 새면 바로 드러난다.
// KST page helpers (static/kst.js) and the page functions that use them: with the browser in New York they must still compute and
// show KST. All network is blocked. Real code slices from the mockup, edu, home and email pages run in a New York page; checks that
// need "now" pin the clock to 2026-10-05T16:00:00Z (= KST Oct 6 01:00, a Tuesday; New York Oct 5 12:00; UTC Oct 5), where the
// calendars disagree on the date, so a slip into browser-local or UTC time shows at once.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8').replace(/\r\n/g, '\n');
const KST_JS = path.join(ROOT, 'static', 'kst.js');
const mockup = read('frontend/ai365-mockup.html');
const edu = read('frontend/ai365-edu-agent.html');
const home = read('frontend/ai365-home.html');
const mcmail = read('frontend/ai365-mcmail.html');
const PINNED = new Date('2026-10-05T16:00:00Z');   // KST 2026-10-06 01:00 (화 / Tue) · New York 2026-10-05 12:00 (EDT)

/* 목업 IIFE 안 2칸 들여쓰기 함수: 한 줄 함수(뒤 주석 포함)는 그 줄, 아니면 '\n  }' 까지
   a two-space indented mockup function: a one-liner (trailing comment included) is its own line, otherwise up to '\n  }' */
function fn(name) {
  const start = mockup.indexOf('  function ' + name + '(');
  assert.ok(start >= 0, name);
  const first = mockup.slice(start, mockup.indexOf('\n', start));
  const open = (first.match(/{/g) || []).length, close = (first.match(/}/g) || []).length;
  return open && open === close ? first : mockup.slice(start, mockup.indexOf('\n  }', start) + 4);
}
/* 접두어로 시작하는 한 줄 / the one line that starts with a prefix */
function lineOf(src, prefix) {
  const i = src.indexOf(prefix);
  assert.ok(i >= 0, prefix);
  return src.slice(i, src.indexOf('\n', i));
}
/* Node 쪽 독립 기준값(도우미를 쓰지 않는다): epoch ms → KST naive ISO / an independent Node-side reference (no helper): epoch ms → KST naive ISO */
const kstIso = ms => new Date(ms + 9 * 3600e3).toISOString().slice(0, 19);

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

/* 뉴욕 시간대 페이지. opts.pin 이면 시계 고정, opts.kst === false 면 kst.js 없이(파일 단독 열람), opts.code 는 그다음에 올릴 코드
   a New York page; opts.pin pins the clock, opts.kst === false leaves kst.js out (a standalone file open), opts.code loads after it */
async function nyPage(t, opts = {}) {
  const ctx = await browser.newContext({ timezoneId: 'America/New_York' });
  t.after(() => ctx.close());
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => route.abort());
  await page.setContent('<!doctype html><meta charset="utf-8"><body></body>');
  if (opts.pin) {
    await page.clock.setFixedTime(PINNED);
    assert.equal(await page.evaluate(() => Date.now()), PINNED.getTime());   // 고정이 실제로 걸렸다 / the pin really applies
  }
  if (opts.kst !== false) await page.addScriptTag({ path: KST_JS });
  if (opts.code) await page.addScriptTag({ content: opts.code });
  return { page, errors };
}

test('kst.js reads, splits and formats on the KST clock while the browser sits in New York', async t => {
  const { page, errors } = await nyPage(t);
  const r = await page.evaluate(() => {
    const at = Date.UTC(2026, 9, 5, 15, 30);   // KST 10/6 00:30 · New York 10/5 11:30
    const a = Date.now(), nowIso = ai365KstIso(), b = Date.now();
    return {
      zone: Intl.DateTimeFormat().resolvedOptions().timeZone, localDate: new Date(at).getDate(),
      parsed: ['2026-10-06T00:30:00', '2026-10-06 00:30:00', '2026-10-06T00:30', '2026-10-05T15:30:00Z', '2026-10-06T00:30:00+09:00']
        .map(s => ai365KstParse(s).toISOString()),
      midnight: ai365KstParse('2026-10-06').toISOString(),
      bad: [ai365KstParse(''), ai365KstParse(null), ai365KstParse(undefined), ai365KstParse('not a date')],
      parts: ai365KstParts(at),
      today: [ai365KstToday(Date.UTC(2026, 9, 5, 16, 0)), ai365KstToday(Date.UTC(2026, 9, 5, 14, 59))],
      iso: [ai365KstIso('2026-10-06T00:30:00'), ai365KstIso('2026-10-06 00:30:00'), ai365KstIso(at)],
      fromParts: ai365KstFromParts(2026, 10, 6, 9, 0).toISOString(),
      addDays: [ai365KstAddDays('2026-10-06', -179), ai365KstAddDays('2026-12-31', 1), ai365KstAddDays('2026-03-01', -1)],
      md: [ai365KstFmt(at, 'md', 'ko'), ai365KstFmt(at, 'md', 'en')],
      ampm: [ai365KstFmt('2026-10-06T15:05:00', 'ampm', 'ko'), ai365KstFmt('2026-10-06T15:05:00', 'ampm', 'en'),
        ai365KstFmt(at, 'ampm', 'ko'), ai365KstFmt(at, 'ampm', 'en')],
      other: [ai365KstFmt(at, 'hm'), ai365KstFmt(at, 'ymdhm'), ai365KstFmt(at, 'long', 'ko'), ai365KstFmt(at, 'long', 'en'), ai365KstFmt(at)],
      now: { a, b, nowIso },
    };
  });
  assert.equal(r.zone, 'America/New_York');
  assert.equal(r.localDate, 5);   // 브라우저 자신의 달력은 아직 5일 / the browser's own calendar still says the 5th
  assert.deepEqual(r.parsed, Array(5).fill('2026-10-05T15:30:00.000Z'));
  assert.equal(r.midnight, '2026-10-05T15:00:00.000Z');   // 날짜만 = KST 자정 / a bare date = KST midnight
  assert.deepEqual(r.bad, [null, null, null, null]);
  assert.deepEqual(r.parts, { y: 2026, m: 10, d: 6, h: 0, mi: 30, s: 0, dow: 2 });
  assert.deepEqual(r.today, ['2026-10-06', '2026-10-05']);
  assert.deepEqual(r.iso, ['2026-10-06T00:30:00', '2026-10-06T00:30:00', '2026-10-06T00:30:00']);
  assert.equal(r.fromParts, '2026-10-06T00:00:00.000Z');
  assert.deepEqual(r.addDays, ['2026-04-10', '2027-01-01', '2026-02-28']);
  assert.deepEqual(r.md, ['10월 6일', 'Oct 6']);
  assert.deepEqual(r.ampm, ['오후 3:05', '3:05 PM', '오전 12:30', '12:30 AM']);
  assert.deepEqual(r.other, ['00:30', '2026-10-06 00:30', '2026년 10월 6일 00:30', 'Oct 6, 2026 00:30', '2026-10-06']);
  assert.ok([kstIso(r.now.a), kstIso(r.now.b)].includes(r.now.nowIso), r.now.nowIso);   // 인자 없으면 지금(KST) / no argument = now in KST
  assert.deepEqual(errors, []);
});

test('mockup collRelTime reads a KST server string from 5 minutes ago as 5 minutes ago in New York', async t => {
  const { page, errors } = await nyPage(t, { pin: true, code: fn('collRelTime') });
  const r = await page.evaluate(() => ({
    five: collRelTime('2026-10-06T00:55:00'),         // 서버 naive 문자열(KST) 5분 전 / a naive server string (KST), 5 minutes ago
    fiveZ: collRelTime('2026-10-05T15:55:00.000Z'),   // 어댑터가 새 채팅에 쓰는 'Z' 문자열 / the 'Z' string the adapter stamps on new chats
    hours: collRelTime('2026-10-05T22:00:00'),
    days: collRelTime('2026-10-04T01:00:00'),
    fresh: collRelTime('2026-10-06T00:59:30'),
    empty: collRelTime(''), bad: collRelTime('garbage'),
    // 종전 계산(Date.parse = 브라우저 로컬)은 뉴욕에서 같은 문자열을 13시간 미래로 읽었다 / the old math (Date.parse = browser local) read it 13 h in the future
    oldMinutes: Math.round((Date.now() - Date.parse('2026-10-06T00:55:00')) / 60000),
  }));
  assert.equal(r.five, '5분 전');
  assert.equal(r.fiveZ, '5분 전');
  assert.equal(r.hours, '3시간 전');
  assert.equal(r.days, '2일 전');
  assert.equal(r.fresh, '방금');
  assert.equal(r.empty, '');
  assert.equal(r.bad, '');
  assert.equal(r.oldMinutes, 5 - 13 * 60);
  assert.deepEqual(errors, []);
});

test('mockup schedule helpers compute now, the past check and the tick windows on the KST clock in New York', async t => {
  const code = ['cdSchedLocalNow', 'cdSchedEpoch', 'cdSchedNotifyPending', 'cdSchedNeedsTick'].map(fn).join('\n');
  const { page, errors } = await nyPage(t, { pin: true, code });
  const r = await page.evaluate(() => {
    const due = s => cdSchedNeedsTick({ schedules: [s] });
    return {
      now0: cdSchedLocalNow(0), now60: cdSchedLocalNow(60),
      ahead: cdSchedEpoch(cdSchedLocalNow(60)) - Date.now(),   // 모달 기본값(+1시간)을 KST 로 다시 읽으면 정확히 1시간 뒤 / the modal default (+1 h) read back as KST is exactly 1 h ahead
      epoch: [cdSchedEpoch('2026-10-06T09:00:00'), cdSchedEpoch('2026-10-06T09:00')],
      unreadable: [cdSchedEpoch(null), cdSchedEpoch(''), cdSchedEpoch('garbage')].map(String),
      // 저장 검사(cdSaveSched): 입력 시각(KST)이 지금 이전이면 막는다 / the save check (cdSaveSched) refuses an entered KST time before now
      past: cdSchedEpoch('2026-10-06T00:59') <= Date.now(), future: cdSchedEpoch('2026-10-06T01:01') <= Date.now(),
      tick: {
        dueSoon: due({ status: 'active', next_run_at: '2026-10-06T01:01:00' }),
        later: due({ status: 'active', next_run_at: '2026-10-06T03:00:00' }),
        overdue: due({ status: 'active', next_run_at: '2026-10-06T00:55:00' }),
        waitNotify: due({ status: 'done', last_run_at: '2026-10-06T00:58:00', last_notify: null }),
        notified: due({ status: 'done', last_run_at: '2026-10-06T00:58:00', last_notify: { at: '2026-10-06T00:59:00' } }),
        staleNotify: due({ status: 'done', last_run_at: '2026-10-06T00:58:00', last_notify: JSON.stringify({ at: '2026-10-06T00:57:00' }) }),
      },
    };
  });
  assert.equal(r.now0, '2026-10-06T01:00');
  assert.equal(r.now60, '2026-10-06T02:00');
  assert.equal(r.ahead, 3600e3);
  assert.deepEqual(r.epoch, [Date.UTC(2026, 9, 6, 0, 0), Date.UTC(2026, 9, 6, 0, 0)]);
  assert.deepEqual(r.unreadable, ['NaN', 'NaN', 'NaN']);
  assert.equal(r.past, true);
  assert.equal(r.future, false);
  assert.deepEqual(r.tick, { dueSoon: true, later: false, overdue: true, waitNotify: true, notified: false, staleNotify: true });
  assert.deepEqual(errors, []);
});

test('mockup stamps (banned-word date, org history, batch-log range) are KST in New York', async t => {
  const code = ['var ABL={};', fn('nowStr'), fn('orgNowStamp'), fn('ablDefaults')].join('\n');
  const { page, errors } = await nyPage(t, { pin: true, code });
  const r = await page.evaluate(() => { ablDefaults(); return { now: nowStr(), org: orgNowStamp(), abl: ABL }; });
  assert.equal(r.now, '2026-10-06 01:00:00');
  assert.equal(r.org, '2026-10-06 01:00');
  assert.deepEqual(r.abl, { from: '2026-04-10', to: '2026-10-06', status: '', page: 1 });   // 최근 180일 / the last 180 days
  assert.deepEqual(errors, []);
});

test('edu page helpers (clock, date offsets, days left, header date) use KST in New York', async t => {
  // EDU_KST = kst.js 가 있는지(파일로 직접 열면 예전 브라우저 시각) / whether kst.js is present (a plain-file open keeps the browser clock)
  const code = ['const EDU_KST=', 'function nowHM(', 'function addDays(', 'function daysUntil('].map(p => lineOf(edu, p))
    .concat(lineOf(edu, 'const dateStr=').replace('const dateStr=', 'window.dateStr=')).join('\n');
  const { page, errors } = await nyPage(t, { pin: true, code });
  const r = await page.evaluate(() => ({
    hm: nowHM(), add: [addDays(0), addDays(1), addDays(-120), addDays(214)],
    left: [daysUntil('2026-10-15'), daysUntil('2026-10-07'), daysUntil('2026-10-05')], bad: String(daysUntil('')),
    date: window.dateStr,
  }));
  assert.equal(r.hm, '01:00');
  assert.deepEqual(r.add, ['2026-10-06', '2026-10-07', '2026-06-08', '2027-05-08']);
  assert.deepEqual(r.left, [9, 1, -1]);
  assert.equal(r.bad, 'NaN');
  assert.equal(r.date, '2026년 10월 6일 화요일');
  assert.deepEqual(errors, []);
});

test('home page today is the KST date in New York; a standalone open without kst.js keeps the browser date', async t => {
  const code = [lineOf(home, 'function pad(n)'), lineOf(home, 'function dkey(d)'), lineOf(home, 'var today=')].join('\n');
  const run = async kst => {
    const { page, errors } = await nyPage(t, { pin: true, kst, code });
    const r = await page.evaluate(() => ({ key: dkey(today), dow: today.getDay(), hours: today.getHours(), local: dkey(new Date()) }));
    assert.deepEqual(errors, []);
    return r;
  };
  assert.deepEqual(await run(true), { key: '2026-10-06', dow: 2, hours: 0, local: '2026-10-05' });    // KST 화요일 / Tuesday in KST
  assert.deepEqual(await run(false), { key: '2026-10-05', dow: 1, hours: 0, local: '2026-10-05' });   // kst.js 없음 = 브라우저 날짜 / no kst.js = the browser's date
});

test('email page today() falls back to the KST date, not the UTC one, when the server META has none', async t => {
  const code = 'var META=null;\n' + lineOf(mcmail, 'const today = () =>');
  const { page, errors } = await nyPage(t, { pin: true, code });
  const r = await page.evaluate(() => {
    const none = today();
    META = { today: '2026-10-01' };
    return { none, server: today(), utc: new Date().toISOString().slice(0, 10) };
  });
  assert.deepEqual(r, { none: '2026-10-06', server: '2026-10-01', utc: '2026-10-05' });   // 종전 대체값(UTC)은 5일 / the old fallback (UTC) said the 5th
  assert.deepEqual(errors, []);
});
