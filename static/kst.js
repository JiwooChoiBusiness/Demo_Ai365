/* 한국 시간(KST) 공통 도우미 — 앱이 보여 주는 모든 시각은 브라우저 시간대와 무관하게 KST(+09:00, 서머타임 없음)다
   (2026-10-06 사용자 지시). 서버는 오프셋 없는 naive 문자열('YYYY-MM-DDTHH:MM:SS')을 KST 벽시계로 보내므로, 그런
   문자열은 +09:00 으로 읽는다. 'Z'·오프셋이 붙은 문자열은 적힌 대로 읽는다. 응답 시점에 <head> 맨 앞에 주입돼
   목업·홈·교육·이메일 화면의 다른 스크립트보다 먼저 정의된다(app/main.py).
   KST helpers — every time the app shows is KST (+09:00, no DST) whatever the browser's zone (user instruction
   2026-10-06). The server sends naive strings ('YYYY-MM-DDTHH:MM:SS') on the KST wall clock, so those are read as
   +09:00; strings carrying 'Z' or an offset are read as written. Injected first in <head> at response time so it is
   defined before the other scripts of the mockup, home, edu and email pages (app/main.py). */
(function () {
  'use strict';
  var OFF = 9 * 3600 * 1000;
  var NAIVE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$/;

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /* 값 → Date. naive 문자열은 KST 벽시계, 숫자는 epoch ms, Date 는 복사 / value → Date (naive = KST wall clock, number = epoch ms) */
  function parse(x) {
    if (x === null || x === undefined || x === '') return null;
    if (x instanceof Date) return isNaN(x.getTime()) ? null : new Date(x.getTime());
    if (typeof x === 'number') return isFinite(x) ? new Date(x) : null;
    var t = String(x).trim();
    var m = NAIVE.exec(t);
    if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)) - OFF);
    var d = new Date(t);
    return isNaN(d.getTime()) ? null : d;
  }

  /* KST 벽시계 조각 {y,m,d,h,mi,s,dow} (dow 0=일) — 인자 없으면 지금 / KST wall-clock parts (dow 0=Sun), now when omitted */
  function parts(x) {
    var d = (x === undefined) ? new Date() : parse(x);
    if (!d) return null;
    var k = new Date(d.getTime() + OFF);
    return { y: k.getUTCFullYear(), m: k.getUTCMonth() + 1, d: k.getUTCDate(), h: k.getUTCHours(),
             mi: k.getUTCMinutes(), s: k.getUTCSeconds(), dow: k.getUTCDay() };
  }

  /* KST naive ISO 'YYYY-MM-DDTHH:MM:SS' — 서버 저장 형식과 같다 / same shape as the server's stored strings */
  function iso(x) {
    var p = parts(x);
    return p ? p.y + '-' + pad(p.m) + '-' + pad(p.d) + 'T' + pad(p.h) + ':' + pad(p.mi) + ':' + pad(p.s) : '';
  }

  /* KST 날짜 'YYYY-MM-DD' / the KST date */
  function today(x) { return iso(x).slice(0, 10); }

  /* KST 벽시계 조각 → Date(시각) / KST wall-clock components → a Date instant */
  function fromParts(y, mo, d, h, mi, s) {
    return new Date(Date.UTC(y, (mo || 1) - 1, d || 1, h || 0, mi || 0, s || 0) - OFF);
  }

  /* 'YYYY-MM-DD' 에 n 일 더하기(KST 달력) / add n days to a KST calendar date */
  function addDays(ymd, n) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(ymd || ''));
    if (!m) return '';
    var k = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3] + (n || 0)));
    return k.getUTCFullYear() + '-' + pad(k.getUTCMonth() + 1) + '-' + pad(k.getUTCDate());
  }

  var MON_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  /* 표시 형식 / display formats
     'ymd' 2026-10-06 · 'hm' 15:30 · 'ymdhm' 2026-10-06 15:30 · 'md' 10월 6일 | Oct 6
     'long' 2026년 10월 6일 15:30 | Oct 6, 2026 15:30 · 'ampm' 오후 3:30 | 3:30 PM */
  function fmt(x, kind, lang) {
    var p = parts(x);
    if (!p) return '';
    var en = lang === 'en';
    var hm = pad(p.h) + ':' + pad(p.mi);
    var h12 = (p.h % 12) || 12;
    switch (kind) {
      case 'hm': return hm;
      case 'ymdhm': return p.y + '-' + pad(p.m) + '-' + pad(p.d) + ' ' + hm;
      case 'md': return en ? MON_EN[p.m - 1] + ' ' + p.d : p.m + '월 ' + p.d + '일';
      case 'long': return en ? MON_EN[p.m - 1] + ' ' + p.d + ', ' + p.y + ' ' + hm
                             : p.y + '년 ' + p.m + '월 ' + p.d + '일 ' + hm;
      case 'ampm': return en ? h12 + ':' + pad(p.mi) + (p.h < 12 ? ' AM' : ' PM')
                             : (p.h < 12 ? '오전 ' : '오후 ') + h12 + ':' + pad(p.mi);
      default: return p.y + '-' + pad(p.m) + '-' + pad(p.d);
    }
  }

  window.ai365KstParse = parse;
  window.ai365KstParts = parts;
  window.ai365KstIso = iso;
  window.ai365KstToday = today;
  window.ai365KstFromParts = fromParts;
  window.ai365KstAddDays = addDays;
  window.ai365KstFmt = fmt;
  window.ai365KstNow = function () { return new Date(); };
})();
