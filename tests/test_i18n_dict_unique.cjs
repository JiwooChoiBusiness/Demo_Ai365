// 실행: node --test tests/test_i18n_dict_unique.cjs
// EN 사전 왕복(2026-10-28): static/adapter.js 의 AI365_KO2EN(+ 뒤의 Object.assign 보탬)은 EN 값이 서로 겹치지 않아야 한다. 역방향 사전(AI365_EN2KO)은
// EN 값마다 KO 하나만 남기므로(뒤 항목이 이긴다) 겹치면 언어를 오갈 때 다른 한국어로 돌아온다(공유하기 → '구성비' 같은 문제). 예약 범위 사전도 같은 규칙.
// EN dictionary round trip (2026-10-28): AI365_KO2EN in static/adapter.js (plus the later Object.assign additions) must not repeat an EN
// value. The reverse map keeps one Korean string per EN value (the later entry wins), so a repeat brings back another Korean string after
// a language switch (Share turning into '구성비'). The schedule-scoped map follows the same rule.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
function literal(name) {
  const a = src.indexOf('const ' + name + ' = {'), b = src.indexOf('\n};', a);
  assert.ok(a >= 0 && b > a, name);
  return vm.runInNewContext('(' + src.slice(src.indexOf('{', a), b + 2) + ')');
}
function dupes(map) {
  const by = {};
  Object.keys(map).forEach(k => { (by[map[k]] = by[map[k]] || []).push(k); });
  return Object.keys(by).filter(v => by[v].length > 1).map(v => v + ' <= ' + by[v].join(' | '));
}

test('every EN value of the global dictionary is unique, so EN to KO returns the original key', () => {
  const map = Object.assign({}, literal('AI365_KO2EN'));
  const re = /Object\.assign\(AI365_KO2EN,\s*\{([\s\S]*?)\}\);/g;
  let m, extra = 0;
  while ((m = re.exec(src))) { Object.assign(map, vm.runInNewContext('({' + m[1] + '})')); extra++; }
  assert.ok(extra >= 1);   // OpenUI 절의 보탬 / the OpenUI section's additions
  assert.ok(Object.keys(map).length > 1500);
  assert.deepEqual(dupes(map), []);
  const back = Object.fromEntries(Object.entries(map).map(([ko, en]) => [en, ko]));
  assert.deepEqual(Object.keys(map).filter(k => back[map[k]] !== k), []);
  // 범위 사전이 맡는 '자동' · Dev 문구로 바뀐 '재개'는 전역에 없다 / '자동' lives in the scoped map; '재개' became Dev's '다시 시작'
  assert.equal(map['자동'], undefined);
  assert.equal(map['재개'], undefined);
  assert.deepEqual([map['공유하기'], map['구성비'], map['지식 관리'], map['완료'], map['선택 완료'], map['다시 시작']],
    ['Share', 'Share of total', 'Knowledge', 'Complete', 'Done', 'Resume']);
});

test('the schedule-scoped dictionary has unique EN values too and still maps the scope pill', () => {
  const sched = literal('AI365_KO2EN_SCHED');
  assert.deepEqual(dupes(sched), []);
  assert.deepEqual([sched['자동'], sched['사내'], sched['외부']], ['Auto', 'Internal', 'External']);
});
