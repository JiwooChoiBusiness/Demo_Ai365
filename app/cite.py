"""사내 문서 각주 귀속 — 답변 문단 ↔ 참조 청크 어휘 대조 (2026-08-24, 에이전트 모드 통합).

파이프라인은 사내 답변에 references [{doc,page}]만 남기고 "어느 문장이 어느 문서에서 왔는지"는 남기지
않는다(외부 grounded 답변만 supports 오프셋이 있음). pipeline.py는 무수정 원칙이라 chats_api가 done
이벤트를 지날 때 여기서 귀속을 계산해 sources에 덧붙인다:
  cites    = 번호 달린 출처 목록 [{n, kind:'knowledge'|'external', title, page, url}]
  supports = [{end: 문단 끝 문자 오프셋, ns:[번호]}] — 어댑터의 기존 각주 렌더 계약과 동일
귀속은 kb 토크나이저(단어 + 한글 2-gram)로 문단 토큰의 참조 청크 포함률을 재는 어휘 대조다 —
임베딩 호출 없이 동기·즉시. 근거가 약한 문단(포함률 < 임계)엔 각주를 달지 않는다(과잉 표기 방지).

Internal-document footnote attribution — lexical matching of answer paragraphs against referenced chunks.
The pipeline only records references [{doc,page}] for internal answers (char-offset supports exist for
external grounded answers only). pipeline.py is frozen, so chats_api computes attribution here as the
'done' event passes through and appends it to sources: cites (numbered source list) + supports (the
adapter's existing footnote contract). Matching uses the kb tokenizer (words + Korean 2-grams) and a
containment ratio — synchronous, no embedding calls. Weak paragraphs get no footnote (no over-marking).
"""

import re

from app import db, kb

MIN_TOKENS = 6        # 이보다 짧은 줄(제목·한 단어)은 귀속 대상에서 제외 / lines shorter than this are skipped
THRESHOLD = 0.34      # 문단 토큰의 참조 청크 포함률 최소값 / minimum containment ratio
SECOND_RATIO = 0.9    # 2순위 출처는 1순위의 이 비율 이상일 때만 함께 표기 / second source only when close to the best


def _chunk_tokens(doc: str, page) -> set[str]:
    with db._conn() as conn:
        if page is None:
            rows = conn.execute("SELECT text FROM kb_chunks WHERE doc = ?", (doc,)).fetchall()
        else:
            rows = conn.execute("SELECT text FROM kb_chunks WHERE doc = ? AND page = ?", (doc, page)).fetchall()
    toks: set[str] = set()
    for r in rows:
        toks.update(kb._tokenize(r["text"] or ""))
    return toks


def _units(text: str) -> list[tuple[int, str]]:
    """귀속 단위 = 비어 있지 않은 줄(마크다운 목록 항목도 한 줄) → (끝 오프셋, 내용). 제목·표·코드 줄 제외."""
    # Attribution units = non-empty lines (list items included) → (end offset, content). Headings/tables/code skipped.
    out, pos, fence = [], 0, False
    for line in text.split("\n"):
        end = pos + len(line)
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
        elif s and not fence and not s.startswith("#") and not s.startswith("|"):
            out.append((end, s))
        pos = end + 1
    return out


def attribute(text: str, references: list[dict]) -> dict | None:
    refs = [r for r in (references or []) if r.get("doc")]
    if not text or not refs:
        return None
    ref_toks = []
    for r in refs:
        try:
            ref_toks.append(_chunk_tokens(str(r["doc"]), r.get("page")))
        except Exception:  # noqa: BLE001 — 청크 조회 실패는 해당 출처만 제외 / a lookup failure only drops that source
            ref_toks.append(set())
    supports = []
    for end, s in _units(text):
        ut = set(kb._tokenize(re.sub(r"[*_`>\-]+", " ", s)))
        if len(ut) < MIN_TOKENS:
            continue
        scored = []
        for i, rt in enumerate(ref_toks):
            if not rt:
                continue
            scored.append((len(ut & rt) / len(ut), i))
        scored.sort(reverse=True)
        if not scored or scored[0][0] < THRESHOLD:
            continue
        best = scored[0][0]
        ns = [scored[0][1] + 1]
        if len(scored) > 1 and scored[1][0] >= THRESHOLD and scored[1][0] >= best * SECOND_RATIO:
            ns.append(scored[1][1] + 1)
        supports.append({"end": end, "ns": sorted(ns)})
    cites = [{"n": i + 1, "kind": "knowledge", "title": str(r["doc"]), "page": r.get("page")} for i, r in enumerate(refs)]
    return {"cites": cites, "supports": supports}


def enrich_sources(sources: dict | None, references: list[dict] | None, text: str) -> dict | None:
    """done.sources에 cites/supports를 덧붙인다(얕은 복사). 이미 supports(웹 grounded)가 있으면 외부 목록만
    번호를 달고 그대로 둔다 — 한 본문에 두 체계의 번호가 섞이지 않게."""
    # Append cites/supports to done.sources (shallow copy). With existing supports (web-grounded) only number the
    # external list and leave the offsets alone — never mix two numbering schemes in one body.
    if not sources:
        return sources
    out = dict(sources)
    ext = out.get("external") or []
    if out.get("supports"):
        out["cites"] = [{"n": s.get("n", i + 1), "kind": "external", "title": s.get("title") or s.get("url") or "",
                         "url": s.get("url") or ""} for i, s in enumerate(ext)]
        return out
    att = attribute(text, references or [])
    if not att:
        if ext:
            out["cites"] = [{"n": s.get("n", i + 1), "kind": "external", "title": s.get("title") or s.get("url") or "",
                             "url": s.get("url") or ""} for i, s in enumerate(ext)]
        return out
    cites = att["cites"]
    k = len(cites)
    for i, s in enumerate(ext):
        cites.append({"n": k + i + 1, "kind": "external", "title": s.get("title") or s.get("url") or "", "url": s.get("url") or ""})
    out["cites"] = cites
    out["supports"] = att["supports"]
    return out
