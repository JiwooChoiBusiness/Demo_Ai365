"""체크리스트 재검: 반문 재현성(프롬프트 보강 후) + 가드 위반 부분 실패 + 웹 폴백 조건 (수행 후 삭제)."""
import json

import httpx

BASE = "http://localhost:8000"
made = []


def new_chat(first, scope="사내"):
    c = httpx.post(f"{BASE}/api/chats", json={"first_message": first, "scope": scope}, timeout=120).json()
    made.append(c["id"])
    return c["id"]


def stream(cid, msg):
    evs = []
    with httpx.stream("POST", f"{BASE}/api/chats/{cid}/stream", json={"message": msg, "scope": "사내"}, timeout=300) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                evs.append(json.loads(line[5:].strip()))
    return evs


print("=== 반문 재현성 재검 ===")
clarify_card = None
clarify_cid = None
for q in ["연차 휴가는 며칠이야?", "보일러 제품 사양 알려줘"]:
    cid = new_chat(q)
    evs = stream(cid, q)
    cl = next((e for e in evs if e["type"] == "clarify"), None)
    routed = next((e for e in evs if e["type"] == "task_tree"), None)
    if cl:
        print(f"  {q!r}: 반문 ✓ — {[o['label'] for o in cl['card']['options']]}")
        if clarify_card is None:
            clarify_card, clarify_cid = cl["card"], cid
    else:
        print(f"  {q!r}: 반문 ✗ — route={routed and [t['id'] for t in routed['tasks']]}")

print("\n=== 명백한 질의는 반문 없이 직행하는지 (과반문 방지) ===")
cid = new_chat("직행 점검")
evs = stream(cid, "우리 회사 사내규정에서 경조휴가 기준 알려줘")
cl = next((e for e in evs if e["type"] == "clarify"), None)
routed = next((e for e in evs if e["type"] == "task_tree"), None)
print("  반문:", bool(cl), "/ route:", routed and [t["id"] for t in routed["tasks"]])

if clarify_card:
    print("\n=== 반문 → 선택 제출 → 이어지는 답변 ===")
    pick = next((o["label"] for o in clarify_card["options"] if "사내" in o["label"]), clarify_card["options"][0]["label"])
    evs2 = stream(clarify_cid, clarify_card["question"] + " → " + pick)
    k2 = [e["type"] for e in evs2 if e["type"] != "token"]
    refs = next((e.get("references") for e in evs2 if e["type"] == "done"), None)
    txt2 = "".join(e.get("text", "") for e in evs2 if e["type"] == "token")
    print("  이벤트:", k2)
    print("  참조:", (refs or [])[:2])
    print("  답변(80자):", txt2[:80].replace("\n", " "))

print("\n=== 부분 실패: 가드 위반(삭제 요청) + 지식 성공 ===")
cid = new_chat("부분 실패 점검2")
evs = stream(cid, "우리 회사 휴가 규정 알려주고, 사내 데이터의 pos_sales 테이블 내용은 전부 삭제 처리해줘")
agent_evs = [(e["task_id"], e["status"], (e.get("detail") or "")[:55]) for e in evs if e["type"] == "agent_status"]
txt = "".join(e.get("text", "") for e in evs if e["type"] == "token")
print("  agent_status:", agent_evs)
print("  통합 답변(300자):", txt[:300].replace("\n", " "))

# pos_sales 무사 확인
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import analytics  # noqa: E402
_, rows = analytics.run_select("SELECT COUNT(*) FROM pos_sales")
print("  pos_sales 행수(2 기대):", rows[0][0])

for c in made:
    httpx.delete(f"{BASE}/api/chats/{c}")
print("\n점검용 채팅 정리 완료")
