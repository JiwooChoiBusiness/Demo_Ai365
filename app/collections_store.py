"""컬렉션(=LLM '프로젝트' 기능) 실 스토어 — 컬렉션·파일·쉐어포인트 링크 영속화 + 채팅 맥락 조합.

컬렉션 채팅은 별도 파이프라인이 아니라 **메인 채팅과 똑같은 파이프라인**을 탄다(2026-07-30 사용자
확정 규약). 이 모듈은 그 앞단 재료만 책임진다: 컬렉션에 등록된 지침·파일 본문·쉐어포인트 링크를
하나의 맥락 블록으로 조합해(context_for) /api/chats/{id}/stream 이 StreamBody.instructions 로
주입한다(pipeline.run_pipeline 의 기존 instructions 계약 재사용 — pipeline.py 무수정).
채팅과의 연결은 chats.coll 컬럼(컬렉션 id 태그)이 담당한다.
"""
# Collections (= LLM "Projects" feature) real store — persists collections/files/SharePoint links and
# composes the chat context. A collection chat rides the SAME pipeline as the main chat (user-confirmed
# contract, 2026-07-30); this module only supplies the up-front material: instructions + file contents +
# SharePoint links composed into one context block (context_for), injected by /api/chats/{id}/stream via
# StreamBody.instructions (reusing run_pipeline's existing instructions contract — pipeline.py untouched).
# The chat linkage lives in the chats.coll column (collection-id tag).

import logging
import uuid

from app import db

logger = logging.getLogger("ai365.collections")

# 맥락 조합 상한 — 프롬프트 비대 방지(파일 본문은 파일당·전체 상한 초과분을 파일명만으로 축약)
# Composition caps — keep the prompt lean (file bodies beyond the per-file/total caps fall back to name-only)
FILE_CONTENT_CAP = 3500
TOTAL_CONTENT_CAP = 9000
INST_CAP = 2000

# ---------------------------------------------------------------------------
# 시드 — 목업 COLLECTIONS 3종과 정합(보도자료 파일 본문은 사용자 제공 시안 캡처의 기사 원문)
# Seeds — match the mockup's three COLLECTIONS (the press-release body comes from the user's capture)
# ---------------------------------------------------------------------------

_PRESS_ARTICLE = (
    "엠클라우드브리지가 출시한 AI 에이전트 교육과정[사진=엠클라우드브리지]\n\n"
    "[디지털데일리 박재현기자] 기업들이 AI 도입을 마치고 '어떻게 쓸 것인가'를 고민하는 단계로 "
    "넘어가면서 임직원 AI 실무 교육에 대한 관심이 늘고 있다. 챗GPT 사용법 중심이던 초기 교육 "
    "시장이 이제 AI 에이전트 구축·운영 역량으로 무게중심을 옮기는 분위기다.\n\n"
    "이러한 가운데 엠클라우드브리지(대표 이혁제)는 12일 기업의 AI 전환을 가속화하기 위한 "
    "'기업 맞춤형 AI 에이전트 교육 프로그램'을 공식 출시했다. 이론 교육에 그치지 않고 수료 즉시 "
    "실무에 투입 가능한 AI 에이전트를 직접 완성하는 실습 중심 구성이 핵심이다.\n\n"
    "교육 과정은 ▲개인 에이전트(Personal Agent) ▲공용 에이전트(Enterprise Agent) ▲전문 업무 "
    "에이전트(Professional AI Agent) 3개 과정으로 구성된다. 개인 업무 자동화부터 조직 단위 "
    "프로세스 혁신, LLM·RAG 기반 에이전트 직접 설계까지 수준별로 나뉜다.\n\n"
    "운영 인프라로는 마이크로소프트 비바 러닝(Viva Learning) 기반 LMS가 제공된다. 팀즈 환경에 "
    "통합돼 업무 중 자연스럽게 학습을 이어갈 수 있으며, AI 파운데이션부터 실전 프로젝트까지 "
    "5단계 러닝 패스로 운영된다."
)

_INVEST_SUMMARY = (
    "요지: 엠클라우드브리지 회사 소개 및 투자 설명 자료(v38).\n"
    "- 회사 개요: Microsoft ERP(Business Central)·Copilot 기반 통합 AI 플랫폼 전문 기업\n"
    "- 제품: Ai365 3.0 — 지식관리·데이터분석·그룹웨어 기본 패키지 + 업무 자동화(커스텀 애드온)\n"
    "- 사업 현황: 통합 AI 플랫폼 사업 고객 확대, 기업 맞춤형 AI 에이전트 교육 프로그램 출시\n"
    "- 전략: ERP를 사용자 업무 환경에서 기업 데이터 플랫폼으로 연결하는 방향의 확장"
)

_SCRAP_SUMMARY = (
    "요지: 최근 보도자료·기사 스크랩 모음.\n"
    "- 엠클라우드브리지, Microsoft ERP + Copilot 기반 통합 AI 플랫폼 사업 고객 확대\n"
    "- 기업 맞춤형 AI 에이전트(AI Agent) 교육 프로그램 공식 출시(개인/공용/전문 3개 과정)\n"
    "- 파트너십 체결·세미나 발표 등 대외 활동 및 업계 평가 스크랩"
)

_SEED_COLLECTIONS = [
    {"id": "col_press", "name": "보도자료", "summary": "보도자료 초안 배포 이력 및 관련 자료를 관리",
     "description": "내부 자료와 참고 정보를 기반으로 일관된 구조와 톤으로 보도자료를 생성하고 관리하는 공간입니다.",
     "inst": "모든 보도자료는 '언론 사용'을 기준으로 작성한다. 사실 기반, 과장 없는 톤을 유지하고 핵심 메시지를 문두에 제시한다.",
     "pinned": 0, "time_label": "6시간 전",
     "files": [
         {"id": "cf_press_release", "name": "[보도자료] 엠클라우드브리지, 기업 맞춤형 AI 에이전트(AI Agent) 출시.docx",
          "content": _PRESS_ARTICLE},
         {"id": "cf_press_invest", "name": "[MCloudBridge] 엠클라우드브리지 투자 설명서_v38.pptx",
          "content": _INVEST_SUMMARY},
         {"id": "cf_press_scrap", "name": "[MCloudBridge] 보도자료 스크랩.pptx",
          "content": _SCRAP_SUMMARY},
     ],
     "links": [
         {"id": "cl_press_dubiz", "url": "dubiz.co.kr/Event/479"},
         {"id": "cl_press_home", "url": "internal.example/Ai365-AI-Agent"},
     ]},
    {"id": "col_news", "name": "뉴스레터", "summary": "뉴스레터 기획안 및 발송 콘텐츠",
     "description": "뉴스레터 콘텐츠를 기획하고 일관된 톤으로 작성·관리하는 공간입니다.",
     "inst": "", "pinned": 0, "time_label": "2개월 전", "files": [], "links": []},
    {"id": "col_content", "name": "컨텐츠", "summary": "SNS, 블로그 및 캠페인 콘텐츠",
     "description": "콘텐츠 자산을 한곳에서 기획·작성·관리하는 공간입니다.",
     "inst": "", "pinned": 0, "time_label": "3개월 전", "files": [], "links": []},
]


def init_collections() -> None:
    with db._conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS coll_collections(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '',
              inst TEXT NOT NULL DEFAULT '',
              pinned INTEGER NOT NULL DEFAULT 0,
              time_label TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS coll_files(
              id TEXT PRIMARY KEY,
              coll_id TEXT NOT NULL REFERENCES coll_collections(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              content TEXT NOT NULL DEFAULT '',
              indexed INTEGER NOT NULL DEFAULT 1,
              pos INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS coll_links(
              id TEXT PRIMARY KEY,
              coll_id TEXT NOT NULL REFERENCES coll_collections(id) ON DELETE CASCADE,
              url TEXT NOT NULL,
              pos INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_coll_files ON coll_files(coll_id, pos);
            CREATE INDEX IF NOT EXISTS idx_coll_links ON coll_links(coll_id, pos);
            """
        )
        # 시드는 최초 1회만(비면) — 이후에는 사용자 편집이 원본이다.
        # Seed only once (when empty) — afterwards the user's edits are the source of truth.
        n = conn.execute("SELECT COUNT(*) AS n FROM coll_collections").fetchone()["n"]
        if n:
            return
        now = db._now()
        for pos, c in enumerate(_SEED_COLLECTIONS):
            conn.execute(
                "INSERT INTO coll_collections(id, name, summary, description, inst, pinned, time_label,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (c["id"], c["name"], c["summary"], c["description"], c["inst"], c["pinned"],
                 c["time_label"], now, now),
            )
            for i, f in enumerate(c["files"]):
                conn.execute(
                    "INSERT INTO coll_files(id, coll_id, name, content, indexed, pos, created_at)"
                    " VALUES(?,?,?,?,1,?,?)",
                    (f["id"], c["id"], f["name"], f["content"], i, now),
                )
            for i, l in enumerate(c["links"]):
                conn.execute(
                    "INSERT INTO coll_links(id, coll_id, url, pos, created_at) VALUES(?,?,?,?,?)",
                    (l["id"], c["id"], l["url"], i, now),
                )
        logger.info("컬렉션 시드 적재: %d개", len(_SEED_COLLECTIONS))


# ---------------------------------------------------------------------------
# 조회/CRUD
# Reads / CRUD
# ---------------------------------------------------------------------------

def _coll_dict(row, files, links) -> dict:
    return {
        "id": row["id"], "name": row["name"], "summary": row["summary"],
        "description": row["description"], "inst": row["inst"], "pinned": bool(row["pinned"]),
        "time_label": row["time_label"], "created_at": row["created_at"],
        "files": [{"id": f["id"], "name": f["name"], "indexed": bool(f["indexed"]),
                   "has_content": bool((f["content"] or "").strip())} for f in files],
        "links": [{"id": l["id"], "url": l["url"]} for l in links],
        # 예약(2026-09-02) — 컬렉션 상세 우측 패널 '예약' 섹션용. 호출자가 연결을 닫은 뒤 _schedules_for 로 채운다.
        # Schedules — for the detail panel's schedule section; the caller fills it via _schedules_for after closing the connection.
        "schedules": [],
    }


def _schedules_for(coll_id: str) -> list[dict]:
    """예약 목록 지연 조회 — schedules 모듈은 이 모듈을 실행 시 지연 임포트하므로 순환 임포트 회피용 지연 임포트.
    실패해도 컬렉션 응답을 막지 않는다(빈 목록)."""
    # Lazy schedule lookup — schedules imports this module at run time, so import lazily here to avoid a cycle.
    # A failure never blocks the collection response (empty list).
    try:
        from app import schedules
        return schedules.list_for_coll(coll_id)
    except Exception:  # noqa: BLE001
        logger.warning("예약 목록 조회 실패(coll=%s) — 빈 목록", coll_id, exc_info=True)
        return []


def _schedules_bulk(coll_ids: list[str]) -> dict[str, list[dict]]:
    """여러 컬렉션의 예약을 한 번에(schedules.list_for_colls — 쿼리 2회·이름 사전 1회). 실패 시 빈 dict(→ 빈 목록)."""
    # Schedules of many collections at once (schedules.list_for_colls — 2 queries + 1 name lookup). Empty dict on failure.
    try:
        from app import schedules
        return schedules.list_for_colls(coll_ids)
    except Exception:  # noqa: BLE001
        logger.warning("예약 목록 일괄 조회 실패 — 빈 목록", exc_info=True)
        return {}


def exists_collection(coll_id: str) -> bool:
    """경량 존재 확인(SELECT 1) — 파일 본문·예약까지 읽는 get_collection 대신 API 의 404 판정용."""
    # Lightweight existence check (SELECT 1) — for API 404 checks, instead of get_collection which loads file bodies and schedules.
    with db._conn() as conn:
        return conn.execute("SELECT 1 FROM coll_collections WHERE id=?", (coll_id,)).fetchone() is not None


def list_collections() -> list[dict]:
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM coll_collections ORDER BY created_at ASC").fetchall()
        out = []
        for r in rows:
            files = conn.execute("SELECT * FROM coll_files WHERE coll_id=? ORDER BY pos, created_at",
                                 (r["id"],)).fetchall()
            links = conn.execute("SELECT * FROM coll_links WHERE coll_id=? ORDER BY pos, created_at",
                                 (r["id"],)).fetchall()
            out.append(_coll_dict(r, files, links))
    # 예약은 N+1 대신 일괄 조회 / schedules are fetched in bulk instead of N+1
    by = _schedules_bulk([c["id"] for c in out])
    for c in out:
        c["schedules"] = by.get(c["id"], [])
    return out


def get_collection(coll_id: str) -> dict | None:
    with db._conn() as conn:
        r = conn.execute("SELECT * FROM coll_collections WHERE id=?", (coll_id,)).fetchone()
        if not r:
            return None
        files = conn.execute("SELECT * FROM coll_files WHERE coll_id=? ORDER BY pos, created_at",
                             (coll_id,)).fetchall()
        links = conn.execute("SELECT * FROM coll_links WHERE coll_id=? ORDER BY pos, created_at",
                             (coll_id,)).fetchall()
    c = _coll_dict(r, files, links)
    c["schedules"] = _schedules_for(coll_id)
    return c


def get_file(coll_id: str, file_id: str) -> dict | None:
    """파일 1건(본문 포함) — 프런트 문서 미리보기용."""
    # Single file (with content) — for the front-end document preview.
    with db._conn() as conn:
        r = conn.execute("SELECT * FROM coll_files WHERE id=? AND coll_id=?", (file_id, coll_id)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "name": r["name"], "content": r["content"], "indexed": bool(r["indexed"])}


def create_collection(name: str, description: str = "", inst: str = "", summary: str = "") -> dict:
    coll_id = "col_" + uuid.uuid4().hex[:10]
    now = db._now()
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO coll_collections(id, name, summary, description, inst, pinned, time_label,"
            " created_at, updated_at) VALUES(?,?,?,?,?,0,'',?,?)",
            (coll_id, name, summary, description, inst, now, now),
        )
    return get_collection(coll_id)


def update_collection(coll_id: str, patch: dict) -> bool:
    fields = {k: v for k, v in patch.items()
              if k in ("name", "summary", "description", "inst", "pinned") and v is not None}
    if not fields:
        return get_collection(coll_id) is not None
    if "pinned" in fields:
        fields["pinned"] = 1 if fields["pinned"] else 0
    sets = ", ".join(f"{k}=?" for k in fields)
    with db._conn() as conn:
        cur = conn.execute(
            f"UPDATE coll_collections SET {sets}, updated_at=? WHERE id=?",  # noqa: S608 — 키는 화이트리스트
            (*fields.values(), db._now(), coll_id),
        )
    return cur.rowcount > 0


def delete_collection(coll_id: str) -> bool:
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM coll_collections WHERE id=?", (coll_id,))
        # 이 컬렉션에 묶였던 채팅은 태그만 해제(대화 자체는 보존)
        # Chats tied to this collection only lose the tag (conversations are preserved)
        conn.execute("UPDATE chats SET coll=NULL WHERE coll=?", (coll_id,))
    return cur.rowcount > 0


def add_file(coll_id: str, name: str, content: str = "") -> dict | None:
    if get_collection(coll_id) is None:
        return None
    fid = "cf_" + uuid.uuid4().hex[:10]
    with db._conn() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(pos)+1,0) AS p FROM coll_files WHERE coll_id=?",
                           (coll_id,)).fetchone()["p"]
        conn.execute(
            "INSERT INTO coll_files(id, coll_id, name, content, indexed, pos, created_at)"
            " VALUES(?,?,?,?,1,?,?)",
            (fid, coll_id, name, content, pos, db._now()),
        )
    return {"id": fid, "name": name, "indexed": True, "has_content": bool(content.strip())}


def remove_file(coll_id: str, file_id: str) -> bool:
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM coll_files WHERE id=? AND coll_id=?", (file_id, coll_id))
    return cur.rowcount > 0


def add_link(coll_id: str, url: str) -> dict | None:
    if get_collection(coll_id) is None:
        return None
    lid = "cl_" + uuid.uuid4().hex[:10]
    with db._conn() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(pos)+1,0) AS p FROM coll_links WHERE coll_id=?",
                           (coll_id,)).fetchone()["p"]
        conn.execute("INSERT INTO coll_links(id, coll_id, url, pos, created_at) VALUES(?,?,?,?,?)",
                     (lid, coll_id, url, pos, db._now()))
    return {"id": lid, "url": url}


def update_link(coll_id: str, link_id: str, url: str) -> bool:
    with db._conn() as conn:
        cur = conn.execute("UPDATE coll_links SET url=? WHERE id=? AND coll_id=?", (url, link_id, coll_id))
    return cur.rowcount > 0


def remove_link(coll_id: str, link_id: str) -> bool:
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM coll_links WHERE id=? AND coll_id=?", (link_id, coll_id))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 채팅 맥락 조합 — stream 엔드포인트가 chats.coll 태그를 보고 호출한다
# Chat-context composition — called by the stream endpoint for chats tagged via chats.coll
# ---------------------------------------------------------------------------

def context_for(coll_id: str, only: list[str] | None = None) -> str:
    """컬렉션 재료(지침·파일 본문·쉐어포인트 링크)를 답변 맥락 블록 하나로 조합한다.

    run_pipeline 이 이 문자열을 "[컬렉션 지침]" 아래에 두고 모든 답변 경로의 시스템 프롬프트로
    흘리므로, 첫 질문·후속 질문 구분 없이 항상 같은 맥락이 유지된다.
    only=컴포저에서 고른 파일 이름. 지정된 파일이 없어도 다른 파일로 범위를 넓히지 않는다."""
    # Composes the collection material (instructions, file bodies, SharePoint links) into one context
    # block. run_pipeline places this under "[컬렉션 지침]" in every answer path's system prompt, so the
    # context persists identically for first and follow-up questions.
    # only = file names picked in the composer's collection attachment — when given, only those bodies ride
    # along. Missing selections never expand to other files.
    c = get_collection(coll_id)
    if not c:
        return ""
    parts = [f"[컬렉션: {c['name']}]"]
    if (c.get("description") or "").strip():
        parts.append(c["description"].strip())
    if (c.get("inst") or "").strip():
        parts.append("컬렉션 지침:\n" + c["inst"].strip()[:INST_CAP])

    files = []
    with db._conn() as conn:
        rows = conn.execute("SELECT name, content FROM coll_files WHERE coll_id=? ORDER BY pos, created_at",
                            (coll_id,)).fetchall()
        files = [(r["name"], (r["content"] or "").strip()) for r in rows]
    narrowed = False
    if only:
        wanted = {str(x).strip() for x in only if str(x).strip()}
        picked = [f for f in files if f[0] in wanted]
        files, narrowed = picked, True
        missing = wanted - {f[0] for f in picked}
        if missing:
            parts.append("선택한 파일을 찾지 못했습니다. 파일을 다시 선택해 주세요: " + ", ".join(sorted(missing)))
    if files:
        lines = [(f"첨부 파일({len(files)}개, 사용자가 고른 파일) — 아래는 사용자가 이 채팅에 첨부한 파일의 본문/요지다. 답변 시 우선 참고한다:"
                  if narrowed else
                  f"첨부 파일({len(files)}개) — 아래는 이 컬렉션에 등록된 파일의 본문/요지다. 답변 시 우선 참고한다:")]
        used = 0
        for name, content in files:
            if content and used < TOTAL_CONTENT_CAP:
                body = content[:FILE_CONTENT_CAP]
                used += len(body)
                lines.append(f"■ {name}\n{body}")
            else:
                # 본문 미등록(사용자 업로드 파일명만 등록) 또는 상한 초과분 — 파일명만 노출
                # No stored body (name-only user upload) or over the cap — expose the name only
                lines.append(f"■ {name} (본문 미등록 — 파일명 참조)")
        parts.append("\n\n".join(lines))

    if c.get("links"):
        parts.append("우선 참고 웹사이트(쉐어포인트 링크):\n"
                     + "\n".join("- " + l["url"] for l in c["links"]))
    return "\n\n".join(parts)
