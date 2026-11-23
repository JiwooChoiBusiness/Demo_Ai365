# -*- coding: utf-8 -*-
"""M코스메틱 이메일 에이전트 화면 테스트 픽스처 캡처 — tests/fixtures/mcmail_api.json.

화면 테스트(tests/test_mcmail_i18n.cjs)는 서버 대신 이 픽스처로 /api/email 을 흉내 낸다. 이 스크립트는 그 응답을 FastAPI
TestClient 로 실제 라우터(app/mcmail_api.py)에서 받아 저장한다. 화면이 보내는 요청이나 서버 응답이 바뀌면 다시 실행한다.
- 격리 DB(tests/db_fixture.isolate_db — 실 DB data/ai365.db 는 건드리지 않는다), 오늘 2026-10-05 고정(시드 기준일 09-20 + 15일:
  서버가 옮긴 날짜·SO 번호가 월을 넘어 바뀌므로 화면 번역이 옮겨진 날짜에도 맞는지 드러난다), ERP 응답 시간 erpMs 고정(837),
  실제 LLM 은 부르지 않는다.
- 상태(state)마다 화면이 보낼 수 있는 GET 전체(메타·대시보드·메일 목록 전 필터·모든 수신 메일 상세·Case 목록 전 필터·모든 Case
  상세·오류·알림·검색 2종)를 기록한다. 흐름(flow)은 테스트가 누를 POST 순서이고, 단계마다 응답과 그 뒤 상태를 남긴다.
- 크기를 줄이려고 80자 이상인 객체·배열은 objs 에 한 번만 두고 {"$ref": n} 으로 가리킨다(구조 중복 제거).
- 요청 키는 화면 스텁과 같은 정규형이다: 빈 값 제외, 이름순, 디코딩한 값('GET /api/email/mails?filter=all&view=inbox').
실행:  .venv/Scripts/python.exe scripts/capture_mcmail_fixtures.py            (픽스처를 다시 쓴다)
       .venv/Scripts/python.exe scripts/capture_mcmail_fixtures.py --check    (쓰지 않고 비교만, 다르면 종료 코드 1)
       .venv/Scripts/python.exe scripts/capture_mcmail_fixtures.py --out 경로  (다른 파일로 쓴다)
처음에는 화면 전환(B2) 작업이 스크래치에서 만들었고 2026-09-28 저장소로 옮겼다.

Captures the Email Agent page-test fixture, tests/fixtures/mcmail_api.json. The page test (tests/test_mcmail_i18n.cjs)
stubs /api/email with this fixture instead of a server; this script records those replies from the real router
(app/mcmail_api.py) through FastAPI's TestClient. Re-run it whenever the page's requests or the server's replies change.
Isolated DB (tests/db_fixture.isolate_db; the real data/ai365.db is never touched), today pinned to 2026-10-05 (seed
base + 15 days, so the server-shifted dates and SO numbers cross a month and the page's translation is exercised on
shifted dates), fixed erpMs (837), no real LLM. Each state records every GET the page can send; each flow is the POST
sequence a test clicks, with the reply and the state after every step. Objects and arrays of 80+ characters are
stored once in objs and referenced as {"$ref": n}. Request keys use the page stub's canonical form (no empty values,
sorted by name, decoded values). --check compares without writing (exit code 1 when different); --out writes elsewhere.
First written in scratch by the page-switch (B2) work and moved into the repository on 2026-09-28.
"""
import argparse
import json
import sys
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))   # 격리 DB 도우미 db_fixture / the isolated-DB helper
sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db_fixture import isolate_db  # noqa: E402
from app import mcmail, mcmail_api  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "mcmail_api.json"
TODAY = date(2026, 10, 5)
ERP_MS_OFFSET = 137            # 조회 시간 고정: erpMs = 700 + 137 = 837 / pinned lookup time
P = "/api/email"
MAIL_VIEWS = ("inbox", "quote", "order", "ship", "stock", "invoice", "etc")
CASE_FILTERS = ("all", "견적", "주문", "문의", "open", "done")
SEARCHES = ("누리", "zzzz")

# 흐름 — 테스트가 누르는 순서 그대로. body 가 함수면 직전 응답으로 만든다(발송 본문 = 서버 초안).
# Flows — exactly the order a test clicks. A callable body is built from the previous reply (send body = server draft).
FLOWS = {
    "enscan": [("/mails/E-1022/erp", {"lang": "en"}),
               ("/mails/E-1022/send", lambda prev: {"draft": prev["email"]["flow"]["draft"]}),
               ("/scenario/2", {"lang": "en"})],
    "drafts": [("/mails/E-1001/erp", {"lang": "en"}), ("/mails/E-1001/draft", {"regen": True, "lang": "en"}),
               ("/mails/E-1022/erp", {"lang": "en"}), ("/mails/E-1022/draft", {"regen": True, "lang": "en"})],
    "kodraft": [("/mails/E-1001/erp", {"lang": "ko"})],
    "koid": [("/mails/E-1016/classify", {"classification": "stock"})],
    "cta": [("/mails/E-1012/complete", None), ("/mails/E-1005/order", None),
            ("/mails/E-1005/draft", {"regen": False, "lang": "ko"}), ("/mails/E-1001/erp", {"lang": "ko"}),
            ("/mails/E-1001/entity", {"field": "quantity", "value": "400"}), ("/mails/E-1001/complete", None)],
    "reset": [("/mails/E-1020/hold", {"on": True}), ("/reset", None)],
}

ABOUT = [
    "M코스메틱 이메일 에이전트 화면 테스트(tests/test_mcmail_i18n.cjs)용 /api/email 응답 픽스처. FastAPI TestClient 로 캡처했다"
    "(격리 DB, 오늘 2026-10-05 고정 = 시드 기준일 + 15일, erpMs 고정, 실제 LLM 없음). gets[i] 요청의 상태별 응답은 states[이름][i], "
    "흐름은 POST 순서와 단계 뒤 상태. {\"$ref\": n} 은 objs[n] 을 가리킨다. 손으로 고치지 말고 "
    "scripts/capture_mcmail_fixtures.py 로 다시 만든다(--check 로 비교만 할 수 있다).",
    "/api/email response fixture for the Email Agent page test (tests/test_mcmail_i18n.cjs), captured with FastAPI's"
    " TestClient (isolated DB, today pinned to 2026-10-05 = seed base + 15 days, fixed erpMs, no real LLM). The reply to"
    " gets[i] in a state is states[name][i]; flows list the POST order and the state after each step. {\"$ref\": n}"
    " points at objs[n]. Regenerate with scripts/capture_mcmail_fixtures.py instead of editing by hand (--check only"
    " compares).",
]


class _Packer:
    """구조 중복 제거기(아래에서 위로, 80자 이상만 objs 에) / bottom-up structural dedup (80+ chars go to objs)"""

    def __init__(self) -> None:
        self.objs: list = []
        self.index: dict = {}

    def pack(self, v):
        if isinstance(v, dict):
            v2 = {k: self.pack(x) for k, x in v.items()}
        elif isinstance(v, list):
            v2 = [self.pack(x) for x in v]
        else:
            return v
        s = json.dumps(v2, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(s) < 80:
            return v2
        i = self.index.get(s)
        if i is None:
            i = self.index[s] = len(self.objs)
            self.objs.append(v2)
        return {"$ref": i}


def key(method: str, path: str, params: dict | None = None) -> str:
    """화면 스텁과 같은 정규 키 — 빈 값 제외, 이름순, 디코딩한 값 / the page stub's canonical key"""
    items = sorted((k, str(v)) for k, v in (params or {}).items() if v not in (None, ""))
    q = "&".join(f"{k}={v}" for k, v in items)
    return f"{method} {P}{path}" + (f"?{q}" if q else "")


def universe(client: TestClient, pk: _Packer) -> dict:
    """지금 상태에서 화면이 보낼 수 있는 GET 전체 / every GET the page can send in the current state"""
    out = {}

    def rec(path, params=None):
        r = client.get(P + path, params=params)
        if r.status_code != 200:
            raise SystemExit(f"GET {path} {params} -> {r.status_code} {r.text[:200]}")
        out[key("GET", path, params)] = pk.pack(r.json())
        return r.json()

    meta = rec("/meta")
    rec("/dashboard", {"date": meta["today"]})
    for v in MAIL_VIEWS:
        for f in (("todo", "all") if v == "inbox" else ("todo", "err", "done", "all")):
            rec("/mails", {"view": v, "filter": f})
    for m in client.get(P + "/mails", params={"view": "inbox", "filter": "all"}).json()["items"]:
        rec(f"/mails/{m['emailId']}")
    for f in CASE_FILTERS:
        rec("/cases", {"filter": f})
    for c in client.get(P + "/cases", params={"filter": "all"}).json()["items"]:
        rec(f"/cases/{c['caseId']}")
    rec("/errors", {"status": "all"})
    rec("/notifications")
    for q in SEARCHES:
        rec("/search", {"q": q})
    return out


def capture() -> dict:
    """픽스처 한 벌을 메모리에서 만든다 / build one fixture in memory"""
    pk = _Packer()
    with ExitStack() as stack:
        isolate_db(stack)
        stack.enter_context(patch.object(mcmail, "_server_today", return_value=TODAY))
        stack.enter_context(patch.object(mcmail.random, "randrange", return_value=ERP_MS_OFFSET))
        stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        mcmail.init_mcmail()
        app = FastAPI()
        app.include_router(mcmail_api.router)
        client = TestClient(app)

        states = {"seed": universe(client, pk)}
        flows = {}
        for name, steps in FLOWS.items():
            client.post(P + "/reset")
            prev, rec_steps = None, []
            for i, (path, body) in enumerate(steps, 1):
                if callable(body):
                    body = body(prev)
                r = client.post(P + path, json=body) if body is not None else client.post(P + path)
                if r.status_code != 200:
                    raise SystemExit(f"POST {path} {body} -> {r.status_code} {r.text[:300]}")
                prev = r.json()
                sname = f"{name}.{i}"
                states[sname] = universe(client, pk)
                rec_steps.append({"req": f"POST {P}{path}", "body": body, "status": r.status_code, "res": pk.pack(prev),
                                  "state": sname})
            flows[name] = rec_steps

    gets = sorted({k for s in states.values() for k in s})
    pos = {k: i for i, k in enumerate(gets)}
    packed_states = {}
    for name, s in states.items():
        row = [None] * len(gets)
        for k, v in s.items():
            row[pos[k]] = v
        packed_states[name] = row
    return {"_about": ABOUT, "today": TODAY.isoformat(), "gets": gets, "states": packed_states, "flows": flows,
            "objs": pk.objs}


def _unpack(fx: dict) -> dict:
    """비교용으로 $ref 를 풀어 (상태 → {요청 키: 응답})·흐름으로 되돌린다 / expand $refs into comparable states and flows"""
    objs = fx["objs"]

    def res(v):
        if isinstance(v, dict):
            if set(v) == {"$ref"}:
                return res(objs[v["$ref"]])
            return {k: res(x) for k, x in v.items()}
        if isinstance(v, list):
            return [res(x) for x in v]
        return v

    states = {n: {k: res(row[i]) for i, k in enumerate(fx["gets"]) if row[i] is not None} for n, row in fx["states"].items()}
    flows = {n: [{**s, "res": res(s["res"])} for s in steps] for n, steps in fx["flows"].items()}
    return {"today": fx["today"], "states": states, "flows": flows}


def compare(old: dict, new: dict) -> list[str]:
    """두 픽스처의 차이를 요청·상태 단위 줄로 / differences between two fixtures, one line per request and state"""
    a, b = _unpack(old), _unpack(new)
    out = []
    if a["today"] != b["today"]:
        out.append(f"today: {a['today']} -> {b['today']}")
    for name in sorted(set(a["states"]) | set(b["states"])):
        sa, sb = a["states"].get(name), b["states"].get(name)
        if sa is None or sb is None:
            out.append(f"state {name}: {'added' if sa is None else 'removed'}")
            continue
        for k in sorted(set(sa) | set(sb)):
            if sa.get(k) != sb.get(k):
                out.append(f"state {name}: {k} {'added' if k not in sa else 'removed' if k not in sb else 'changed'}")
    for name in sorted(set(a["flows"]) | set(b["flows"])):
        fa, fb = a["flows"].get(name), b["flows"].get(name)
        if fa != fb:
            out.append(f"flow {name}: " + ("added" if fa is None else "removed" if fb is None else "changed"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="M코스메틱 이메일 에이전트 화면 테스트 픽스처 캡처 / capture the page-test fixture")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 비교만(다르면 종료 코드 1) / compare only, exit 1 when different")
    ap.add_argument("--out", type=Path, default=OUT, help="출력 경로 / output path")
    args = ap.parse_args()
    fixture = capture()
    size = len(fixture["gets"]), len(fixture["states"]), len(fixture["objs"])
    if args.check:
        if not args.out.exists():
            raise SystemExit(f"{args.out} 가 없습니다 / missing")
        diffs = compare(json.loads(args.out.read_text(encoding="utf-8")), fixture)
        print(f"captured gets {size[0]}, states {size[1]}, objs {size[2]} | differences vs {args.out.name}: {len(diffs)}")
        for line in diffs[:200]:
            print("  " + line)
        raise SystemExit(1 if diffs else 0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes): gets {size[0]}, states {size[1]}, objs {size[2]}")


if __name__ == "__main__":
    main()
