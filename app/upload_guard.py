"""업로드 검증(2026-10-01, 관리 센터 › 로컬 설정 › 업로드 검증).

Public 영역(리소스 센터 지식 관리)에 올리는 파일을 미리 검사해 보안 정책에 어긋나는 문서의 업로드를 막는다.
  - 검사 방식: 키워드 포함 여부(LLM 없음). 파일명과 문서 본문 글자를 모두 본다 — 대소문자를 가리지 않고, 키워드 글자가
    그대로 들어 있으면 걸린다(띄어쓰기는 맞춰 주지 않는다).
  - 본문 글자: PDF(pymupdf), Word · PowerPoint · Excel(압축 안 XML 의 글자, 외부 엔티티 차단), TXT. 글자를 뽑을 수 없으면
    (그림 PDF 등) 파일명만 본다.
  - 판정: 일반 사용자 · 관리자 = 차단(어떤 키워드인지는 알려 주지 않는다), 슈퍼어드민 = 경고(키워드 · 설명 · 위치) 후 본인이
    고르면 업로드(force). 슈퍼어드민의 force 도 서버가 다시 슈퍼인지 본다.
  - 저장: upload_guard_keywords(키워드 · 설명(경고 창에 쓰는 글, LLM 이 읽지 않음) · 사용 여부), upload_guard_meta(사용 토글).
    처음 기동 때 키워드 10개를 1회 넣고 검증을 켠다(2026-10-01 사용자 결정). 예외 키워드는 두지 않는다.
  - 설정 API 는 슈퍼어드민 전용(키워드 목록도 슈퍼에게만 보인다). /check 는 문서 관리 화면의 업로드(화면 데모 추가)가 먼저 묻는 검사.

Upload validation (2026-10-01, Admin Center › Local settings › Upload validation).
Files uploaded to the Public area (Resource Center knowledge) are checked first, and documents that break the security policy
are kept out.
  - Keyword matching only (no LLM), over the file name and the document text: case-insensitive, the keyword's characters as
    they are (spacing is not normalized).
  - Text: PDF (pymupdf), Word, PowerPoint and Excel (text in the archive's XML, external entities refused), TXT. Without
    extractable text (an image PDF, for one) only the file name is checked.
  - Verdict: users and admins are blocked (the keywords are not revealed); the super admin gets a warning (keywords,
    descriptions, where) and may upload anyway (force), which the server checks against the super identity again.
  - Store: upload_guard_keywords (keyword, description shown in the warning and never read by an LLM, enabled) and
    upload_guard_meta (the on/off switch). Ten keywords are seeded once on first start with validation on (user decision
    2026-10-01). There are no exception keywords.
  - The settings API is super-admin only (the keyword list is shown to the super admin only). /check is the pre-check the
    document-management screen's upload (a client-side demo add) asks first.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import unicodedata
import uuid
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from lxml import etree
from pydantic import BaseModel

from app import db, kst

logger = logging.getLogger("ai365.upload_guard")

router = APIRouter(prefix="/api/upload-guard", tags=["upload-guard"])

MAX_KEYWORDS = 200
MAX_KEYWORD_LEN = 40
MAX_DESC_LEN = 100
MAX_BYTES = 50_000_000        # = resources_api.MAX_PDF_BYTES (업로드 상한과 같게) / the upload cap
MAX_TEXT = 3_000_000          # 본문에서 읽는 글자 상한 / characters read from a document
MAX_UNZIPPED = 60 * 1024 * 1024
TEXT_EXTS = ("pdf", "docx", "pptx", "xlsx", "txt")
WHERE_NAME, WHERE_TEXT = "파일명", "문서 내용"
BLOCK_LOG_REASON = "보안 정책 위반으로 업로드 차단"
# 처음 1회 넣는 키워드(2026-10-01 사용자 결정: 시안의 10개) / the ten keywords seeded once (user decision 2026-10-01)
SEED = (("개인정보", "개인정보 관련 문서"), ("주민등록번호", "개인 식별 정보"), ("계좌번호", "금융정보"),
        ("신용카드", "금융정보"), ("고객정보", "고객 관련 민감정보"), ("기밀", "회사 기밀정보"),
        ("대외비", "외부 공개 금지 문서"), ("인사정보", "임직원 관련 정보"), ("계약서", "계약 관련 민감문서"),
        ("재무정보", "재무 및 회계 정보"))


def _now() -> str:
    return kst.now_iso()


def _key(s: str) -> str:
    """비교용 글자 — NFC · 대소문자 무시 / the comparison form: NFC, case-folded"""
    return unicodedata.normalize("NFC", s or "").casefold()


def init_upload_guard() -> None:
    """테이블 생성(멱등) + 처음 1회 키워드 10개 · 검증 켬 / tables (idempotent) and the one-time seed with validation on"""
    with db._conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS upload_guard_keywords(id TEXT PRIMARY KEY, keyword TEXT NOT NULL, "
                     "description TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, "
                     "updated TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS upload_guard_meta(k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        if conn.execute("SELECT 1 FROM upload_guard_meta WHERE k = 'seeded'").fetchone():
            return
        now = _now()
        for word, desc in SEED:
            conn.execute("INSERT INTO upload_guard_keywords(id, keyword, description, enabled, created, updated) VALUES (?,?,?,?,?,?)",
                         ("ug_" + uuid.uuid4().hex[:8], word, desc, 1, now, now))
        conn.execute("INSERT OR REPLACE INTO upload_guard_meta(k, v) VALUES ('enabled', '1')")
        conn.execute("INSERT OR REPLACE INTO upload_guard_meta(k, v) VALUES ('seeded', '1')")


def _row(r) -> dict:
    return {"id": r["id"], "keyword": r["keyword"], "description": r["description"], "enabled": bool(r["enabled"])}


def is_enabled() -> bool:
    with db._conn() as conn:
        r = conn.execute("SELECT v FROM upload_guard_meta WHERE k = 'enabled'").fetchone()
    return bool(r) and r["v"] == "1"


def list_keywords() -> list[dict]:
    with db._conn() as conn:
        return [_row(r) for r in conn.execute("SELECT * FROM upload_guard_keywords ORDER BY rowid").fetchall()]


def settings() -> dict:
    return {"enabled": is_enabled(), "keywords": list_keywords(), "limits": {"keyword": MAX_KEYWORD_LEN, "description": MAX_DESC_LEN}}


def set_enabled(on: bool) -> bool:
    with db._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO upload_guard_meta(k, v) VALUES ('enabled', ?)", ("1" if on else "0",))
    return bool(on)


def _clean_keyword(value) -> str:
    word = unicodedata.normalize("NFC", str(value or "")).strip()
    if not word:
        raise ValueError("키워드를 입력하세요")
    if len(word) > MAX_KEYWORD_LEN:
        raise ValueError(f"키워드는 {MAX_KEYWORD_LEN}자까지입니다")
    if any(ch in word for ch in "\r\n\t"):
        raise ValueError("키워드에는 줄바꿈을 쓸 수 없습니다")
    return word


def _clean_desc(value) -> str:
    desc = re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or ""))).strip()
    if len(desc) > MAX_DESC_LEN:
        raise ValueError(f"설명은 {MAX_DESC_LEN}자까지입니다")
    return desc


def _taken(conn, word: str, skip: str = "") -> bool:
    return any(_key(r["keyword"]) == _key(word) and r["id"] != skip
               for r in conn.execute("SELECT id, keyword FROM upload_guard_keywords").fetchall())


def add_keyword(keyword, description="", enabled: bool = True) -> dict:
    word, desc = _clean_keyword(keyword), _clean_desc(description)
    with db._conn() as conn:
        if conn.execute("SELECT COUNT(*) AS n FROM upload_guard_keywords").fetchone()["n"] >= MAX_KEYWORDS:
            raise ValueError(f"키워드는 {MAX_KEYWORDS}개까지 등록할 수 있습니다")
        if _taken(conn, word):
            raise LookupError(f"이미 등록된 키워드입니다: {word}")
        kid, now = "ug_" + uuid.uuid4().hex[:8], _now()
        conn.execute("INSERT INTO upload_guard_keywords(id, keyword, description, enabled, created, updated) VALUES (?,?,?,?,?,?)",
                     (kid, word, desc, 1 if enabled else 0, now, now))
        return _row(conn.execute("SELECT * FROM upload_guard_keywords WHERE id = ?", (kid,)).fetchone())


def update_keyword(kid: str, keyword=None, description=None, enabled=None) -> dict | None:
    with db._conn() as conn:
        cur = conn.execute("SELECT * FROM upload_guard_keywords WHERE id = ?", (kid,)).fetchone()
        if cur is None:
            return None
        word = _clean_keyword(keyword) if keyword is not None else cur["keyword"]
        desc = _clean_desc(description) if description is not None else cur["description"]
        on = (1 if enabled else 0) if enabled is not None else cur["enabled"]
        if keyword is not None and _taken(conn, word, kid):
            raise LookupError(f"이미 등록된 키워드입니다: {word}")
        conn.execute("UPDATE upload_guard_keywords SET keyword = ?, description = ?, enabled = ?, updated = ? WHERE id = ?",
                     (word, desc, on, _now(), kid))
        return _row(conn.execute("SELECT * FROM upload_guard_keywords WHERE id = ?", (kid,)).fetchone())


def delete_keyword(kid: str) -> bool:
    with db._conn() as conn:
        return conn.execute("DELETE FROM upload_guard_keywords WHERE id = ?", (kid,)).rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# 본문 글자 / document text
# ─────────────────────────────────────────────────────────────────────────────

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
# 문단(글자 조각을 이어 붙이는 단위)과 그 안의 글자 / paragraphs (where runs are joined) and the text inside them
_OOXML = {
    "docx": (re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml"), f"{{{_W}}}p", f"{{{_W}}}t"),
    "pptx": (re.compile(r"ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml"), f"{{{_A}}}p", f"{{{_A}}}t"),
    "xlsx": (re.compile(r"xl/(sharedStrings|worksheets/sheet\d+)\.xml"), f"{{{_S}}}si", f"{{{_S}}}t"),
}

def _ooxml_text(data: bytes, fmt: str) -> str:
    parts, para_tag, text_tag = _OOXML[fmt]
    parser = etree.XMLParser(resolve_entities=False, no_network=True)   # 파서는 스레드마다 따로 / one parser per call (not thread-safe)
    out, size = [], 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = [i for i in zf.infolist() if parts.fullmatch(i.filename)]
        if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED * 4 or len(zf.infolist()) > 5000:
            raise ValueError("압축 해제 크기가 너무 큰 파일입니다")
        for info in entries:
            size += info.file_size
            if size > MAX_UNZIPPED:
                break
            raw = zf.read(info)
            if b"<!DOCTYPE" in raw[:4096].upper():
                continue   # 문서 형식 선언(엔티티)이 있는 부분은 읽지 않는다 / parts with a DOCTYPE (entities) are skipped
            root = etree.fromstring(raw, parser=parser)
            if fmt == "xlsx":   # 공유 문자열(si) + 시트의 인라인 문자열(is) / shared strings and inline strings
                blocks = root.iter(para_tag, f"{{{_S}}}is")
            else:
                blocks = root.iter(para_tag)
            for p in blocks:
                line = "".join(t.text or "" for t in p.iter(text_tag))
                if line:
                    out.append(line)
    return "\n".join(out)


def _pdf_text(data: bytes) -> str:
    import fitz  # pymupdf

    out, size = [], 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text("text")
            out.append(text)
            size += len(text)
            if size >= MAX_TEXT:
                break
    return "\n".join(out)


def _txt_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def document_text(filename: str, data: bytes) -> str:
    """문서 본문 글자(대문자 · 소문자 그대로). 형식 밖이거나 읽지 못하면 '' — 그때는 파일명만 검사한다.
    The document's text; '' when the format is not covered or reading fails, in which case only the file name is checked."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in TEXT_EXTS or not data:
        return ""
    try:
        if ext == "pdf":
            text = _pdf_text(data)
        elif ext == "txt":
            text = _txt_text(data)
        else:
            text = _ooxml_text(data, ext)
    except Exception:  # noqa: BLE001 — 깨진 파일 · 압축 폭탄 · 암호 걸린 문서는 파일명만 본다 / broken, bombed or locked files: name only
        logger.info("업로드 검증: 본문을 읽지 못해 파일명만 검사합니다 (%s)", filename, exc_info=True)
        return ""
    return text[:MAX_TEXT]


# ─────────────────────────────────────────────────────────────────────────────
# 검사 / the check
# ─────────────────────────────────────────────────────────────────────────────

def scan(filename: str, text: str) -> list[dict]:
    """켜진 키워드 중 파일명 · 본문에 들어 있는 것 — [{keyword, description, where:[파일명|문서 내용]}] (표 순서)
    The enabled keywords found in the file name or text, in table order."""
    name_key, text_key = _key(filename), _key(re.sub(r"\s*\n\s*", " ", text or ""))
    hits = []
    for k in list_keywords():
        if not k["enabled"]:
            continue
        word = _key(k["keyword"])
        where = ([WHERE_NAME] if word in name_key else []) + ([WHERE_TEXT] if word in text_key else [])
        if where:
            hits.append({"keyword": k["keyword"], "description": k["description"], "where": where})
    return hits


def verdict(filename: str, data: bytes, is_super: bool, force: bool = False) -> dict:
    """업로드 판정 — ok | blocked(일반 사용자 · 관리자, 키워드는 알려 주지 않음) | warn(슈퍼어드민, 키워드 · 설명 · 위치).
    슈퍼어드민이 경고를 보고 고른 업로드(force)는 ok. 검증이 꺼져 있거나 켜진 키워드가 없으면 본문을 읽지 않고 ok.
    The upload verdict: ok, blocked (users and admins; keywords withheld) or warn (super admin; keywords, descriptions and
    where). A super admin's confirmed upload (force) is ok. Off, or no enabled keyword: ok without reading the text."""
    if not is_enabled() or not any(k["enabled"] for k in list_keywords()):
        return {"result": "ok"}
    hits = scan(filename, document_text(filename, data))
    if not hits:
        return {"result": "ok"}
    if not is_super:
        return {"result": "blocked"}
    if force:
        logger.info("업로드 검증: 슈퍼어드민이 경고를 보고 업로드 (%s, %s)", filename, ", ".join(h["keyword"] for h in hits))
        return {"result": "ok", "forced": True}
    return {"result": "warn", "hits": hits}


def is_super(acting_user_id: str) -> bool:
    """뷰애즈 없이 쓰는 '나'(숫자 아닌 acting id) = 슈퍼어드민 — resources_api._eff 와 같은 규칙 / same rule as resources_api._eff"""
    aid = (acting_user_id or "").strip()
    return not aid or not aid.isdigit()


# ─────────────────────────────────────────────────────────────────────────────
# API — 설정은 슈퍼어드민 전용 / settings are super-admin only
# ─────────────────────────────────────────────────────────────────────────────

def _require_super(acting_user_id: str) -> None:
    if not is_super(acting_user_id):
        raise HTTPException(status_code=403, detail="슈퍼관리자 전용 기능입니다")


class EnabledIn(BaseModel):
    acting_user_id: str = ""
    enabled: bool = True


class KeywordIn(BaseModel):
    acting_user_id: str = ""
    keyword: str | None = None
    description: str | None = None
    enabled: bool | None = None


@router.get("")
def get_settings(acting_user_id: str = "") -> dict:
    _require_super(acting_user_id)
    return settings()


@router.put("/enabled")
def put_enabled(body: EnabledIn) -> dict:
    _require_super(body.acting_user_id)
    return {"enabled": set_enabled(body.enabled)}


@router.post("/keywords")
def post_keyword(body: KeywordIn) -> dict:
    _require_super(body.acting_user_id)
    try:
        return {"keyword": add_keyword(body.keyword, body.description or "", True if body.enabled is None else body.enabled)}
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.patch("/keywords/{kid}")
def patch_keyword(kid: str, body: KeywordIn) -> dict:
    _require_super(body.acting_user_id)
    try:
        row = update_keyword(kid, body.keyword, body.description, body.enabled)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail="키워드를 찾을 수 없습니다")
    return {"keyword": row}


@router.delete("/keywords/{kid}")
def remove_keyword(kid: str, acting_user_id: str = "") -> dict:
    _require_super(acting_user_id)
    if not delete_keyword(kid):
        raise HTTPException(status_code=404, detail="키워드를 찾을 수 없습니다")
    return {"ok": True}


@router.post("/check")
async def check(file: UploadFile = File(...), acting_user_id: str = Form("")) -> dict:
    """업로드 전 검사(문서 관리 화면의 업로드가 먼저 묻는다) — 저장하지 않는다. 슈퍼어드민에게만 키워드를 알려 준다.
    The pre-upload check the document-management screen asks first; nothing is stored, and only the super admin learns the keywords."""
    name = unicodedata.normalize("NFC", file.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=422, detail=f"파일이 너무 큽니다(최대 {MAX_BYTES // 1_000_000}MB)")
    out = await asyncio.to_thread(verdict, name, data, is_super(acting_user_id))
    return {"file": name, **out}
