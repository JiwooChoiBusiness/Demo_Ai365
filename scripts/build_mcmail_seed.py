"""[역사 기록용 · 실행 불가] M코스메틱 이메일 에이전트 첫 시드(app/mcmail_seed.json)를 만든 스크립트.

2026-09-28 첫 시드는 이 스크립트가 화면 원본의 데이터 구간(const TODAY … hadIssues 계산, SCN)을 Node vm 으로 평가해
만들었다(생성자 F/A/C/IN/OUT 포함, 절대 날짜는 app.mcmail._tokenize 로 기준일 대비 토큰, 시나리오 build 의 현재 Case
수량·납기는 __QTY__·__DD__ 자리표시). 같은 날 화면(frontend/ai365-mcmail.html)이 서버 API 를 쓰도록 바뀌면서 그 데이터
구간이 사라져 더는 실행할 수 없다. 지금은 app/mcmail_seed.json 이 원천이다 — 시드를 고칠 때는 그 JSON 을 직접 고친다
(날짜 토큰 문법은 JSON 의 _about). 아래 코드는 첫 시드가 어떻게 만들어졌는지 보여 주는 기록으로만 남긴다(main 은 안내 후
종료한다).

[Historical record, cannot run] The script that generated the first M Cosmetic Email Agent seed
(app/mcmail_seed.json). On 2026-09-28 it evaluated the original page's data section with a Node vm (constructors
included, absolute dates tokenized with app.mcmail._tokenize, the scenario builders' current case quantity and date
left as __QTY__ / __DD__ placeholders). The same day the page (frontend/ai365-mcmail.html) moved to the server API and
lost that section, so this can no longer run. app/mcmail_seed.json is now the source: edit that JSON directly (date
token grammar in its _about). The code below stays only as a record of how the first seed was made; main() prints a
notice and exits.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import mcmail  # noqa: E402

HTML = ROOT / "frontend" / "ai365-mcmail.html"
OUT = ROOT / "app" / "mcmail_seed.json"

# 데이터 구간 평가 — 마커 줄로 범위를 잡고 vm 에서 실행한 뒤 전역을 JSON 으로 내보낸다.
# Data-section evaluation — markers bound the range; the vm run exports the globals as JSON.
_JS = r"""
'use strict';
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(process.env.MCMAIL_HTML, 'utf8');
const lines = html.split(/\r?\n/);
function find(re, from) { for (let i = from || 0; i < lines.length; i++) if (re.test(lines[i])) return i; throw new Error('marker not found: ' + re); }
const a = find(/^const TODAY = '/);
const b = find(/^EMAILS\.forEach\(e => \{ e\.hadIssues = issues\(e\)\.length > 0; \}\);/, a);
const s0 = find(/^const SCN_CASE = '/, b);
const s1 = find(/^function scnState\(/, s0);
function seq(name) { const m = new RegExp('^let ' + name + ' = (\\d+);', 'm').exec(html); if (!m) throw new Error('seq ' + name); return Number(m[1]); }
function literal(re, what, open, close) { const m = re.exec(html); if (!m) throw new Error(what); return vm.runInNewContext(open + m[1] + close); }
const shipEn = Object.fromEntries(literal(/^\s*(\['[^']+', 'Preparing shipment'\],.*?),?\s*$/m, 'ship states', '[', ']'));
const progEn = literal(/const PROG = (\{[^}]*\});/, 'PROG', '(', ')');
const exportCode = `
globalThis.__OUT = JSON.stringify({
  TODAY, clock, mailSeq, errSeq, caseSeq: ${seq('caseSeq')}, soSeq: ${seq('soSeq')},
  USERS, TIERS, ERP_ITEMS, ERP_CUSTOMERS, CONTACTS, SHIPMENTS, SIGX, MC_SIG,
  CLS, ERPMETA, CASE_OPTIONAL, INTENTS, FIELDS, FIELDSETS, REQUIRED, ERR_CATS,
  CASES, EMAILS, ERRORS, LOG, SCN_CASE,
  SCN: SCN.map(s => ({ n: s.n, title: s.title, emailId: s.emailId, quote: s.quote, ai: s.ai, flow: s.flow,
    build: s.build ? s.build({ entity: { quantity: '__QTY__', deliveryDate: '__DD__' } }) : null }))
});`;
const code = lines.slice(a, b + 1).join('\n') + '\n' + lines.slice(s0, s1).join('\n') + '\n' + exportCode;
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(code, ctx, { filename: 'mcmail-data-section.js' });
const out = JSON.parse(ctx.__OUT);
out.SHIP_STATE_EN = shipEn;
out.PROG_EN = progEn;
process.stdout.write(JSON.stringify(out));
"""

_MASTERS = ("USERS", "TIERS", "ERP_ITEMS", "ERP_CUSTOMERS", "CONTACTS", "SIGX", "MC_SIG", "CLS", "ERPMETA", "CASE_OPTIONAL",
            "INTENTS", "FIELDS", "FIELDSETS", "REQUIRED", "ERR_CATS", "SHIP_STATE_EN", "PROG_EN")


def main() -> None:
    """실행하면 안내만 하고 끝낸다 — 시드는 JSON 을 직접 고친다 / prints a notice and exits; edit the seed JSON directly."""
    raise SystemExit("scripts/build_mcmail_seed.py 는 역사 기록용이라 실행할 수 없습니다. 시드는 app/mcmail_seed.json 을 직접 "
                     "고치세요(날짜 토큰 문법은 그 파일의 _about). / This historical script cannot run; edit "
                     "app/mcmail_seed.json directly (date token grammar in its _about).")


def _first_seed_build() -> None:
    """[기록] 2026-09-28 첫 시드를 만든 절차 — 부르지 않는다(데이터 구간이 없는 지금 화면에서는 실패하고, 원본 화면을
    되살려 돌리면 손으로 고친 JSON 을 덮어쓴다).
    [Record] the procedure that built the first seed on 2026-09-28; never called (it fails on today's page, and run
    against a restored original page it would overwrite the hand-edited JSON)."""
    res = subprocess.run(["node", "-e", _JS], capture_output=True, check=True, env={**os.environ, "MCMAIL_HTML": str(HTML)})
    raw = json.loads(res.stdout.decode("utf-8"))
    base = date.fromisoformat(raw["TODAY"])
    body = {
        "clock": raw["clock"],
        "seq": {"mail": raw["mailSeq"], "case": raw["caseSeq"], "err": raw["errSeq"], "so": raw["soSeq"], "msg": 0},
        "masters": {k: raw[k] for k in _MASTERS},
        "SHIPMENTS": raw["SHIPMENTS"], "CASES": raw["CASES"], "EMAILS": raw["EMAILS"], "ERRORS": raw["ERRORS"],
        "LOG": raw["LOG"], "SCN_CASE": raw["SCN_CASE"], "SCN": raw["SCN"],
    }
    seed = {
        "_about": [
            "M코스메틱 Email Agent 시드 — scripts/build_mcmail_seed.py 가 frontend/ai365-mcmail.html 의 데이터 구간을 Node 로 "
            "평가해 만든다(손으로 고치지 말 것). 날짜는 base 대비 토큰: [[D±n]] YYYY-MM-DD, [[C±n]] YYYYMMDD, [[Y±n]] YYYY-MM"
            "(개월), [[K±n]] 'M월 D일', [[S±n]] 'M/D', [[M±n]] MMDD, [[E±n]] 'Month D'. 시드·초기화 때 서버의 오늘로 복원한다.",
            "M Cosmetic Email Agent seed, generated by scripts/build_mcmail_seed.py from the data section of "
            "frontend/ai365-mcmail.html (do not edit by hand). Dates are tokens relative to base and are restored to the "
            "server's today on seed and reset.",
        ],
        "base": raw["TODAY"],
        **mcmail._tokenize(body, base),  # noqa: SLF001 — 같은 날짜 문법을 공유 / shares the date grammar
    }
    OUT.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes): emails {len(raw['EMAILS'])}, cases {len(raw['CASES'])}, "
          f"errors {len(raw['ERRORS'])}, log {len(raw['LOG'])}, scenario {len(raw['SCN'])}")


if __name__ == "__main__":
    main()
