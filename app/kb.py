"""지식관리 인덱스 — PDF 텍스트 추출/청킹/임베딩(SQLite 저장) + 하이브리드 검색.

- 인덱싱: PyMuPDF로 페이지별 텍스트 추출 → 600자/오버랩 120자 청킹 → Gemini 배치 임베딩
- 증분식: 파일 해시(kb_docs)로 처리 완료 PDF 스킵. 문서 단위 트랜잭션이라 중단 후 재실행 가능
- 검색: 질의 임베딩 코사인 top-k(numpy) + rank-bm25 키워드 점수의 가중 합산
"""
# Knowledge-management index — PDF text extraction/chunking/embedding (stored in SQLite) + hybrid search.
#
# - Indexing: extract text per page with PyMuPDF -> chunk into 600 chars / 120-char overlap -> Gemini batch embedding
# - Incremental: skip already-processed PDFs via file hash (kb_docs). Per-document transactions allow resuming after interruption
# - Search: weighted sum of query-embedding cosine top-k (numpy) + rank-bm25 keyword scores

import hashlib
import logging
import re
import threading
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from app import db, kst, llm, settings

logger = logging.getLogger("ai365.kb")

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"
EMBED_INSERT_BATCH = 32  # 임베딩+저장 진행 단위(진행 로그/부분 저장)
# Embedding+save progress unit (progress logging / partial save)

_index_lock = threading.Lock()
_cache_lock = threading.Lock()
_cache: dict = {"key": None, "chunks": [], "matrix": None, "bm25": None}


# ---------------------------------------------------------------------------
# 인덱싱
# Indexing
# ---------------------------------------------------------------------------

def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _chunk_text(text: str) -> list[str]:
    """600자 슬라이딩 윈도우(오버랩 120자) 청킹."""
    # Chunk with a 600-char sliding window (120-char overlap).
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    size, overlap = settings.KB_CHUNK_SIZE, settings.KB_CHUNK_OVERLAP
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    step = size - overlap
    while start < len(text):
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
        start += step
    return chunks


def _extract_pages(path: Path) -> list[tuple[int, str]]:
    """(페이지 번호(1부터), 텍스트) 목록."""
    # List of (page number (1-based), text).
    import fitz  # pymupdf

    pages = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            pages.append((i, page.get_text("text")))
    return pages


def _index_one(path: Path, actor: str = "시스템") -> bool:
    """PDF 1개 인덱싱. 변경 없으면 False(스킵), 인덱싱했으면 True. 처리 이력은 kb_log(AI Batch Log, 2026-09-16)에 남긴다."""
    # Index a single PDF. Returns False (skip) if unchanged, True if indexed. The run is recorded in kb_log (AI Batch Log).
    from app import kb_log  # 지연 임포트(순환 방지) / lazy import (avoids a cycle)
    name = path.name
    file_hash = _file_hash(path)
    with db._conn() as conn:
        row = conn.execute("SELECT hash FROM kb_docs WHERE doc = ?", (name,)).fetchone()
    if row and row["hash"] == file_hash:
        logger.info("스킵(변경 없음): %s", name)
        return False

    logger.info("인덱싱 시작: %s", name)
    log_id = kb_log.start(name, actor)
    try:
        pages = _extract_pages(path)
        items: list[tuple[int, str]] = []  # (page, chunk_text)
        for page_no, text in pages:
            for chunk in _chunk_text(text):
                items.append((page_no, chunk))
        logger.info("  %d페이지 → %d청크", len(pages), len(items))

        # 재인덱싱/중단 후 재실행 대비: 기존(또는 부분) 청크 제거 후 새로 적재
        # For re-indexing / resuming after interruption: remove existing (or partial) chunks, then load fresh
        with db._conn() as conn:
            conn.execute("DELETE FROM kb_chunks WHERE doc = ?", (name,))
            conn.execute("DELETE FROM kb_docs WHERE doc = ?", (name,))

        for i in range(0, len(items), EMBED_INSERT_BATCH):
            batch = items[i : i + EMBED_INSERT_BATCH]
            vectors = llm.embed([t for _, t in batch])  # 키 로테이션·무료 한도 sleep은 llm.embed가 처리
            # Key rotation and free-tier-limit sleeps are handled by llm.embed
            with db._conn() as conn:
                conn.executemany(
                    "INSERT INTO kb_chunks(doc, page, text, vector) VALUES(?, ?, ?, ?)",
                    [
                        (name, page, text, np.asarray(vec, dtype=np.float32).tobytes())
                        for (page, text), vec in zip(batch, vectors)
                    ],
                )
            logger.info("  임베딩 진행: %d/%d", min(i + EMBED_INSERT_BATCH, len(items)), len(items))

        # 문서 완료 마킹 — 여기 도달하기 전에 중단되면 다음 실행에서 이 문서만 다시 처리된다
        # Mark document as complete — if interrupted before reaching here, only this document is reprocessed on the next run
        with db._conn() as conn:
            conn.execute(
                "INSERT INTO kb_docs(doc, hash, pages, chunks, indexed_at) VALUES(?, ?, ?, ?, ?)",
                (name, file_hash, len(pages), len(items), kst.now_iso()),
            )
    except Exception as exc:
        kb_log.finish(log_id, error=kb_log.error_reason(exc))   # 오류 행(사유 한 줄) / error row with a one-line reason
        raise
    # 텍스트가 전혀 없는 PDF(이미지 전용)는 색인은 남기되 이력은 오류로 표시한다 / an image-only PDF stays indexed but is logged as an error
    kb_log.finish(log_id, pages=len(pages), chunks=len(items), error=None if items else kb_log.NO_TEXT_REASON)
    logger.info("완료: %s (%d청크)", name, len(items))
    return True


def index_all() -> dict:
    """data/knowledge/의 모든 PDF를 증분 인덱싱. 삭제된 문서는 정리."""
    # Incrementally index all PDFs in data/knowledge/. Clean up deleted documents.
    with _index_lock:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(KNOWLEDGE_DIR.glob("*.pdf"))
        stats = {"indexed": 0, "skipped": 0, "removed": 0, "failed": 0}

        # 폴더에서 사라진 문서 정리
        # Clean up documents that disappeared from the folder
        names = {p.name for p in pdfs}
        with db._conn() as conn:
            stale = [r["doc"] for r in conn.execute("SELECT doc FROM kb_docs").fetchall() if r["doc"] not in names]
            for doc in stale:
                conn.execute("DELETE FROM kb_chunks WHERE doc = ?", (doc,))
                conn.execute("DELETE FROM kb_docs WHERE doc = ?", (doc,))
                logger.info("제거(파일 없음): %s", doc)
            stats["removed"] = len(stale)

        for path in pdfs:
            try:
                if _index_one(path):
                    stats["indexed"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                logger.exception("인덱싱 실패: %s — 다음 문서 계속", path.name)
                stats["failed"] += 1

        logger.info("인덱싱 종료: %s", stats)
        return stats


def index_all_background() -> None:
    """서버 기동 시 백그라운드 자동 인덱싱(기동 차단 방지)."""
    # Auto-index in the background at server startup (to avoid blocking startup).
    threading.Thread(target=index_all, name="kb-indexer", daemon=True).start()


def index_one_background(path: Path, actor: str = "시스템") -> None:
    """업로드된 PDF 1개를 백그라운드에서 인덱싱 — 부팅 인덱서(index_all)와 _index_lock 으로 직렬화.

    임베딩이 무료 한도 sleep 으로 수십 초 걸릴 수 있어 요청 동기 처리 대신 스레드로 돌린다.
    완료 여부는 kb_docs 등재로 판단(GET /api/resources/knowledge/index-status). actor = AI Batch Log 의 등록자(업로드한 사람)."""
    # Index a single uploaded PDF in the background — serialized with the boot indexer via _index_lock.
    # Embedding can take tens of seconds (free-tier sleeps), so run in a thread instead of blocking the request.
    # Completion is observed via kb_docs (GET /api/resources/knowledge/index-status). actor = the uploader shown in the AI Batch Log.
    def run() -> None:
        with _index_lock:
            try:
                _index_one(path, actor)
            except Exception:
                logger.exception("업로드 인덱싱 실패: %s", path.name)

    threading.Thread(target=run, name="kb-index-one", daemon=True).start()


# ---------------------------------------------------------------------------
# 검색
# Search
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """BM25용 토크나이저 — 단어 + 한글 2-gram(조사/어미 변형 대응)."""
    # Tokenizer for BM25 — words + Korean 2-grams (to handle particle/ending variations).
    words = re.findall(r"[가-힣a-zA-Z0-9]+", text.lower())
    tokens = list(words)
    for w in words:
        if re.fullmatch(r"[가-힣]{3,}", w):
            tokens.extend(w[i : i + 2] for i in range(len(w) - 1))
    return tokens


def _load_cache() -> dict:
    """청크/벡터 행렬/BM25를 메모리 캐시. 인덱스 변경 자동 감지."""
    # Memory-cache chunks / vector matrix / BM25. Auto-detect index changes.
    with db._conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n, MAX(indexed_at) AS t FROM kb_docs").fetchone()
        key = (row["n"], row["t"])
        with _cache_lock:
            if _cache["key"] == key:
                return _cache
            rows = conn.execute("SELECT doc, page, text, vector FROM kb_chunks ORDER BY id").fetchall()
            chunks = [{"doc": r["doc"], "page": r["page"], "text": r["text"]} for r in rows]
            if rows:
                matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                matrix = matrix / np.clip(norms, 1e-8, None)
                bm25 = BM25Okapi([_tokenize(c["text"]) for c in chunks])
            else:
                matrix, bm25 = None, None
            _cache.update({"key": key, "chunks": chunks, "matrix": matrix, "bm25": bm25})
            logger.info("KB 캐시 갱신: %d청크", len(chunks))
            return _cache


def search(query: str, top_k: int | None = None) -> list[dict]:
    """하이브리드 검색. similarity(원시 코사인)는 근거 강도 판단용, score는 정렬용."""
    # Hybrid search. similarity (raw cosine) is for judging evidence strength; score is for sorting.
    cache = _load_cache()
    if not cache["chunks"]:
        return []
    top_k = top_k or settings.KB_TOP_K

    qv = np.asarray(llm.embed([query])[0], dtype=np.float32)
    qv = qv / max(float(np.linalg.norm(qv)), 1e-8)
    cos = cache["matrix"] @ qv  # 정규화 행렬이라 내적=코사인
    # Since the matrix is normalized, dot product = cosine

    bm = np.asarray(cache["bm25"].get_scores(_tokenize(query)), dtype=np.float32)
    bm_norm = bm / bm.max() if bm.max() > 0 else bm
    cos_norm = np.clip(cos, 0, None)

    w = settings.KB_VECTOR_WEIGHT
    hybrid = w * cos_norm + (1 - w) * bm_norm

    order = np.argsort(-hybrid)[:top_k]
    return [
        {**cache["chunks"][int(i)], "similarity": float(cos[int(i)]), "score": float(hybrid[int(i)])}
        for i in order
    ]
