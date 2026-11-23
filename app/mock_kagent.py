"""가상 고객 배포 — 로컬 지식 에이전트(2026-09-29, 계획 A3 · 구현 계약 5절). 서버 안에 두는 "고객 환경"의 Knowledge
MCP Server 와 Knowledge API Server 한 벌을 테넌트 2곳(hq 본사 · lab 연구소)으로 흉내 낸다. 관리 센터 › 로컬 설정의
지식 에이전트 등록 → 연결 테스트 → 리소스 센터 Local 탭(폴더 · 문서 · 미리보기 · 다운로드 · 업로드 · 삭제)을 실제 고객
시스템 없이 시연하기 위한 것이다.

  - 인증(MCP · API 공통): Authorization: Bearer demo-kagent-key-2026, X-API-Key: demo-kagent-key-2026, 또는 OAuth 로 받은
    토큰(POST /{tenant}/oauth/token, client_credentials). 아니면 401. 값은 데모 표시값이다(실제 비밀이 아니다).
  - MCP(POST /{tenant}/mcp, JSON-RPC): initialize · notifications/initialized(202) · ping · tools/list · tools/call.
    도구 3종 kb_chat · kb_search · kb_get_document(입력 · 출력 명세, readOnlyHint). kb_chat 은 문서 본문 키워드 발췌로
    만든 결정적 답변 + 출처이고 외부 LLM 을 부르지 않는다(model 표기만 hq · lab 모두 Qwen 3.5-4B — 2026-10-06).
  - API(/{tenant}/api/v1): GET /health · /folders · /documents · /documents/{id}/status|preview|download,
    POST /documents(multipart), DELETE /documents/{id}.
  - 저장: SQLite mock_kagent_docs(text = 검색용 본문, content = 원본 바이트). 시드는 테넌트마다 1회(mock_kagent_meta 플래그,
    지워도 다시 생기지 않는다). 업로드 직후 processing, created_at 5초 뒤 done(읽을 때 계산).
  - handle(tenant, msg, authorization, api_key) 는 HTTP 없이 부르는 JSON-RPC 처리 함수다(테스트가 그대로 부른다).

Fictional customer deployment for local knowledge agents (2026-09-29, plan A3, contract section 5). One "customer
environment" (Knowledge MCP Server + Knowledge API Server) hosted inside the app for two tenants (hq head office, lab
research center), so the Admin Center local-settings registration, the connection test and the Resource Center Local tab
(folders, documents, preview, download, upload, delete) can be demonstrated without a real customer system.
  - Auth (MCP and API alike): Authorization: Bearer demo-kagent-key-2026, X-API-Key: demo-kagent-key-2026, or a token from
    POST /{tenant}/oauth/token (client_credentials); anything else is 401. The values are demo display values.
  - MCP (POST /{tenant}/mcp, JSON-RPC): initialize, notifications/initialized (202), ping, tools/list, tools/call. Three
    tools kb_chat, kb_search, kb_get_document with input/output schemas and readOnlyHint. kb_chat builds a deterministic
    answer plus sources from keyword excerpts; no external LLM call (only the model label differs per tenant).
  - API (/{tenant}/api/v1): GET /health, /folders, /documents, /documents/{id}/status|preview|download,
    POST /documents (multipart), DELETE /documents/{id}.
  - Storage: SQLite mock_kagent_docs (text = searchable body, content = original bytes). Seeded once per tenant (flag in
    mock_kagent_meta; deleted seeds never come back). Uploads are processing until 5 s after created_at, then done
    (computed on read).
  - handle(tenant, msg, authorization, api_key) is the HTTP-free JSON-RPC handler that tests call directly.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import hmac
import io
import json
import logging
import re
import sqlite3
import time
import unicodedata
import uuid
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app import kst
from app.db import DB_PATH
from app.mock_apis import MockAPIError, MockAPIRoute

logger = logging.getLogger("ai365.mock_kagent")
router = APIRouter(prefix="/mock/kagent", tags=["mock-kagent"], route_class=MockAPIRoute)

# 데모 표시값(실제 비밀이 아니다) — 로컬 설정 화면의 데모 채우기와 시드 에이전트가 쓴다
# Demo display values (not real secrets) used by the local-settings demo fill and the seeded agent
DEMO_KEY = "demo-kagent-key-2026"
OAUTH_CLIENT_ID = "ai365-demo"
OAUTH_CLIENT_SECRET = "local-demo-oauth-only"
TOKEN_TTL = 3600                                   # OAuth 토큰 수명(초) / OAuth token lifetime (seconds)
_TOKEN_SIGNING_KEY = b"ai365-kagent-demo-token-signing"   # 무상태 토큰 서명(재시작에도 유효) / stateless token signature (survives restarts)
PROCESSING_SEC = 5                                 # 업로드 후 처리 완료까지 / upload → done delay
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 200_000                           # 검색용 본문 상한 / cap on the searchable text
PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
CAPABILITIES = ("list", "upload", "preview", "download", "delete", "status")
FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts" / "pretendard"

TENANTS: dict[str, dict] = {
    "hq": {"label": "본사", "model": "Qwen 3.5-4B",
           "server_info": {"name": "본사 Knowledge MCP Server (가상)", "version": "1.0.0"}},
    "lab": {"label": "연구소", "model": "Qwen 3.5-4B",
            "server_info": {"name": "연구소 Knowledge MCP Server (가상)", "version": "1.0.0"}},
}

EXT_MIME = {
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
    "hwp": "application/x-hwp", "hwpx": "application/hwp+zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
TEXT_MIMES = ("text/plain", "text/markdown")

# ────────────────────────────────────────────────────────
# 폴더 · 시드 문서 / folders and seed documents
# ────────────────────────────────────────────────────────

FOLDERS: dict[str, list[dict]] = {
    "hq": [
        {"id": "hq-rules", "name": "경영 규정", "children": [{"id": "hq-security", "name": "보안 정책", "children": []}]},
        {"id": "hq-sales", "name": "영업 자료", "children": []},
    ],
    "lab": [
        {"id": "lab-research", "name": "연구 과제", "children": [{"id": "lab-battery", "name": "배터리 소재", "children": []}]},
        {"id": "lab-manual", "name": "실험 매뉴얼", "children": []},
    ],
}

# 문서 1개 = id · 폴더 · 이름(확장자로 형식 결정) · 날짜 · 부제(PDF 머리) · 본문 문단. 표(xlsx)는 rows.
# One document = id, folder, name (the extension decides the format), date, subtitle (PDF header), body paragraphs; rows for the xlsx.
SEED_DOCS: dict[str, list[dict]] = {
    "hq": [
        {"id": "hq-doc-001", "folder_id": "hq-rules", "name": "정보보안 기본 규정.pdf", "date": "2026-03-02T09:10:00",
         "subtitle": "본사 · 경영 규정 · 2026-03-02 개정",
         "paragraphs": [
             "제1조(목적) 이 규정은 회사의 정보자산을 보호하고 정보보안 사고를 예방하기 위하여 임직원이 지켜야 할 기본 원칙과 "
             "책임을 정한다. 정보보안 책임자는 매년 1회 이상 이 규정이 현재 업무 환경에 맞는지 검토하고 필요하면 개정안을 올린다.",
             "제2조(계정과 비밀번호) 모든 임직원은 개인에게 발급된 계정만 사용하며 계정을 다른 사람과 공유해서는 안 된다. "
             "비밀번호는 영문 대소문자, 숫자, 특수문자를 조합해 10자 이상으로 설정하고 90일마다 변경한다. "
             "5회 연속으로 인증에 실패하면 계정이 30분 동안 잠긴다.",
             "제3조(단말기와 저장매체) 업무용 노트북은 디스크 암호화와 10분 화면 잠금을 적용해야 한다. 회사 승인 없이 USB 등 "
             "이동식 저장매체로 업무 자료를 반출할 수 없으며, 반출이 꼭 필요하면 정보보안팀의 사전 승인을 받는다.",
             "제4조(사고 보고) 악성코드 감염, 자료 유출 의심, 계정 도용 같은 보안 사고를 알게 된 임직원은 즉시 정보보안팀"
             "(내선 2580)에 보고한다. 정보보안팀은 24시간 안에 1차 조치 결과를 정보보안 책임자에게 보고한다.",
         ]},
        {"id": "hq-doc-002", "folder_id": "hq-security", "name": "개인정보 처리 지침.pdf", "date": "2026-03-16T14:20:00",
         "subtitle": "본사 · 보안 정책 · 2026-03-16 시행",
         "paragraphs": [
             "이 지침은 고객과 임직원의 개인정보를 수집, 이용, 보관, 파기하는 모든 단계에서 지켜야 할 절차를 정한다. "
             "개인정보는 업무 목적에 필요한 최소한의 범위에서만 수집하고, 수집할 때 이용 목적과 보유 기간을 알리고 동의를 받는다.",
             "주민등록번호와 계좌번호 같은 고유식별정보와 금융정보는 암호화해 저장하고, 조회 권한은 해당 업무에 꼭 필요한 인원으로 "
             "제한한다. 개인정보 처리 시스템의 접속 기록은 최소 2년 동안 보관한다.",
             "보유 기간이 끝났거나 처리 목적을 달성한 개인정보는 5영업일 안에 복구할 수 없는 방법으로 파기하고, 파기 결과를 "
             "개인정보 보호책임자에게 보고한다. 외부 업체에 처리를 맡길 때는 위탁 계약서에 안전조치 의무를 명시한다.",
         ]},
        {"id": "hq-doc-003", "folder_id": "hq-sales", "name": "2026 영업 전략 보고서.pdf", "date": "2026-01-12T10:00:00",
         "subtitle": "본사 · 영업 자료 · 2026-01-12 경영회의 보고",
         "paragraphs": [
             "2026년 영업 목표는 매출 1,850억 원으로 전년보다 12% 성장하는 것이다. 성장의 핵심 동력은 제조와 유통 고객사의 "
             "AI 도입 수요이며, 신규 고객 40곳 확보와 기존 고객 재계약률 92% 유지를 함께 목표로 한다.",
             "중점 시장은 수도권 중견 제조사와 영남권 산업단지 고객이다. 상반기에는 파일럿 제안으로 접점을 넓히고, 하반기에는 "
             "파일럿 성공 사례를 근거로 전사 확산 계약으로 전환한다.",
             "영업 조직은 산업별 3개 팀으로 재편하고, 제안 단계부터 기술 담당자가 함께 참여하는 2인 1조 방식을 기본으로 한다. "
             "분기마다 파이프라인 전환율과 평균 계약 기간을 점검해 목표 달성 여부를 관리한다.",
         ]},
        {"id": "hq-doc-004", "folder_id": "hq-sales", "name": "고객 미팅 기록 가이드.txt", "date": "2026-02-05T16:40:00",
         "subtitle": "",
         "paragraphs": [
             "고객 미팅 기록 가이드",
             "고객 미팅이 끝나면 24시간 안에 CRM에 미팅 기록을 등록한다. 기록에는 참석자, 논의 안건, 고객의 요구사항, "
             "합의한 다음 단계와 기한을 반드시 넣는다.",
             "가격이나 계약 조건처럼 민감한 내용은 확정된 사항과 협의 중인 사항을 나누어 적는다. 고객이 공유한 자료는 원본을 "
             "첨부하되, 개인정보가 들어 있는 자료는 개인정보 처리 지침에 따라 가린 뒤 첨부한다.",
             "미팅 기록은 팀장이 매주 1회 검토하고, 다음 단계 기한이 지난 건은 담당자에게 알림이 간다.",
         ]},
        {"id": "hq-doc-005", "folder_id": "hq-sales", "name": "고객사 제안서 양식.hwp", "date": "2026-02-20T11:15:00",
         "subtitle": "",
         "paragraphs": [
             "고객사 제안서 양식. 제안 개요, 고객 현황과 과제, 제안 솔루션, 추진 일정, 기대 효과, 견적 요약 순서로 작성하는 "
             "본사 표준 제안서 양식이다.",
         ]},
    ],
    "lab": [
        {"id": "lab-doc-001", "folder_id": "lab-research", "name": "차세대 배터리 소재 연구 계획서.pdf", "date": "2026-02-27T10:30:00",
         "subtitle": "연구소 · 연구 과제 · 2026-02-27 승인",
         "paragraphs": [
             "이 과제는 전기차용 차세대 배터리의 에너지 밀도를 높이기 위해 고니켈 양극재와 실리콘 복합 음극재를 개발하는 것을 "
             "목표로 한다. 연구 기간은 2026년 3월부터 2027년 12월까지 22개월이며 총 연구비는 38억 원이다.",
             "1단계에서는 니켈 함량 90% 이상 양극재의 합성 조건을 최적화하고, 2단계에서는 실리콘 함량 15% 음극재의 부피 팽창을 "
             "억제하는 코팅 공정을 개발한다. 단계가 끝날 때마다 셀 단위 평가로 성능 목표를 달성했는지 판단한다.",
             "최종 목표는 셀 기준 에너지 밀도 350Wh/kg, 1,000회 충방전 뒤 용량 유지율 85% 이상이다. 연구 결과는 특허 출원과 "
             "사업부 기술 이전을 거쳐 양산 공정에 적용한다.",
         ]},
        {"id": "lab-doc-002", "folder_id": "lab-battery", "name": "소재 시험 결과 요약.pdf", "date": "2026-07-08T17:05:00",
         "subtitle": "연구소 · 배터리 소재 · 2026년 2분기 시험",
         "paragraphs": [
             "2026년 2분기 시험에서는 고니켈 양극재 시료 12종과 실리콘 복합 음극재 시료 8종을 평가했다. 양극재 NCM-92 시료는 "
             "초기 방전 용량 221mAh/g으로 목표치 215mAh/g을 넘었다.",
             "음극재 SiC-15 시료는 100회 충방전 뒤 용량 유지율 91%를 기록했지만, 45도 고온 조건에서는 84%로 떨어져 코팅 두께 "
             "조정이 필요하다. 다음 분기에는 코팅 두께를 세 가지 조건으로 나누어 다시 시험한다.",
             "시험 데이터 원본은 연구소 데이터 서버의 소재 시험 폴더에 보관하며, 시료 번호와 시험 조건을 파일 이름에 함께 적는다.",
         ]},
        {"id": "lab-doc-003", "folder_id": "lab-manual", "name": "실험실 안전 수칙.pdf", "date": "2026-01-19T09:00:00",
         "subtitle": "연구소 · 실험 매뉴얼 · 2026-01-19 개정",
         "paragraphs": [
             "실험실에 들어갈 때는 보안경, 실험복, 내화학 장갑을 반드시 착용한다. 리튬 금속과 전해액을 다루는 작업은 건조실이나 "
             "글러브박스 안에서만 한다.",
             "화학물질은 물질안전보건자료(MSDS)를 확인한 뒤 사용하고, 사용이 끝나면 지정된 보관함에 넣어 잠근다. 폐전해액과 "
             "폐용매는 성상별로 나누어 폐액 용기에 모으고, 매월 1회 전문 업체가 수거한다.",
             "화재나 누출 사고가 나면 즉시 작업을 멈추고 비상벨을 누른 뒤 실험실 밖으로 대피한다. 리튬 화재에는 물을 쓰지 말고 "
             "D급 소화기를 사용한다. 사고가 수습되면 연구소 안전관리자에게 사고 보고서를 낸다.",
         ]},
        {"id": "lab-doc-004", "folder_id": "lab-manual", "name": "장비 사용 매뉴얼.txt", "date": "2026-04-22T13:45:00",
         "subtitle": "",
         "paragraphs": [
             "충방전 시험기 사용 매뉴얼",
             "충방전 시험기는 사용 전에 예약 시스템에서 채널을 예약하고, 시험 조건(전류, 전압 범위, 사이클 수)을 등록한 뒤 가동한다. "
             "예약하지 않은 채널은 임의로 쓰지 않는다.",
             "시험 중 온도 경보가 울리면 해당 채널을 일시 정지하고 셀 상태를 확인한다. 셀이 부풀었거나 누액이 보이면 시험을 멈추고 "
             "안전 수칙에 따라 격리해 보관한다.",
             "장비 교정은 분기마다 장비 담당자가 하며, 교정 기록은 장비 옆 점검표와 연구소 장비 관리 시스템에 함께 남긴다.",
         ]},
        {"id": "lab-doc-005", "folder_id": "lab-manual", "name": "특허 출원 현황.xlsx", "date": "2026-08-31T15:30:00",
         "subtitle": "",
         "paragraphs": [],
         "rows": [
             ["출원번호", "발명의 명칭", "출원일", "상태", "담당 연구원"],
             ["10-2026-0012345", "고니켈 양극재의 제조 방법", "2026-02-14", "심사 중", "서지민"],
             ["10-2026-0023456", "실리콘 복합 음극재의 코팅 구조", "2026-04-03", "출원 완료", "권민서"],
             ["10-2026-0034567", "전해액 첨가제 조성물과 이를 포함하는 이차전지", "2026-06-21", "출원 준비", "황시우"],
         ]},
    ],
}


def seed_count(tenant: str) -> int:
    """테넌트의 시드 문서 수(시드 에이전트의 doc_count) / seed document count of a tenant (the seeded agent's doc_count)"""
    return len(SEED_DOCS.get(tenant) or [])


# ────────────────────────────────────────────────────────
# 시드 원본 만들기 / building the seed originals
# ────────────────────────────────────────────────────────

def _pdf_bytes(title: str, subtitle: str, paragraphs: list[str]) -> bytes:
    """A4 PDF 1장(PyMuPDF + 프로젝트 Pretendard 글꼴 임베드). 글꼴 파일이 없으면 FileNotFoundError.
    One A4 PDF page (PyMuPDF with the project's embedded Pretendard font). FileNotFoundError when the font files are missing."""
    import fitz

    reg, bold = FONT_DIR / "Pretendard-Regular.otf", FONT_DIR / "Pretendard-Bold.otf"
    if not reg.is_file() or not bold.is_file():
        raise FileNotFoundError("Pretendard 글꼴 파일이 없습니다")
    reg_s, bold_s = str(reg), str(bold)
    W, H, M = 595, 842, 56
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_font(fontname="kr", fontfile=reg_s)
    page.insert_font(fontname="krb", fontfile=bold_s)
    page.insert_textbox(fitz.Rect(M, 60, W - M, 100), title, fontname="krb", fontfile=bold_s, fontsize=18, color=(0.1, 0.12, 0.18))
    if subtitle:
        page.insert_textbox(fitz.Rect(M, 100, W - M, 120), subtitle, fontname="kr", fontfile=reg_s, fontsize=9.5, color=(0.42, 0.45, 0.52))
    page.draw_line(fitz.Point(M, 128), fitz.Point(W - M, 128), color=(0.8, 0.82, 0.86), width=0.8)
    y = 144
    for para in paragraphs:
        box_h = H - 70 - y
        if box_h < 40:
            break
        rest = page.insert_textbox(fitz.Rect(M, y, W - M, y + box_h), para, fontname="kr", fontfile=reg_s,
                                   fontsize=10.5, lineheight=1.7, color=(0.12, 0.13, 0.16))
        if rest < 0:   # 넘치면 거기서 멈춘다(시드 본문은 한 장에 들어간다) / stop on overflow (seed bodies fit one page)
            break
        y += (box_h - rest) + 12
    page.insert_textbox(fitz.Rect(M, H - 44, W - M, H - 26), "가상 고객 배포 데모 문서", fontname="kr", fontfile=reg_s,
                        fontsize=8, color=(0.6, 0.62, 0.66), align=2)
    try:
        pdf.subset_fonts()
    except Exception:  # noqa: BLE001 — 서브셋 실패는 용량만 손해 / a failed subset only costs size
        logger.warning("가상 지식 에이전트 PDF 글꼴 서브셋 실패", exc_info=True)
    try:
        return pdf.tobytes(garbage=3, deflate=True)
    finally:
        pdf.close()


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    """openpyxl 로 만든 실제 xlsx(없으면 ImportError) / a real xlsx built with openpyxl (ImportError when unavailable)"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "출원 현황"
    for row in rows:
        ws.append(row)
    for col, width in zip("ABCDE", (18, 40, 12, 10, 12)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _hwp_dummy(text: str) -> bytes:
    """미리보기가 안 되는 형식의 더미 원본(OLE 서명 + 본문) / a dummy original for a non-previewable format (OLE signature + text)"""
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504 + text.encode("utf-16-le")


@functools.lru_cache(maxsize=None)
def _seed_payload(tenant: str, doc_id: str) -> tuple[str, str, bytes, str]:
    """시드 문서 1개의 (이름, MIME, 원본, 검색용 본문). 프로세스마다 1번만 만든다. PDF 를 못 만들면(글꼴·PyMuPDF 없음) .txt 로 대체.
    (name, MIME, original bytes, searchable text) of one seed document, built once per process. Falls back to .txt when
    the PDF cannot be built (missing font or PyMuPDF)."""
    d = next(x for x in SEED_DOCS[tenant] if x["id"] == doc_id)
    name, paras = d["name"], list(d.get("paragraphs") or [])
    ext = name.rsplit(".", 1)[-1].lower()
    if d.get("rows"):
        text = "\n".join(" ".join(r) for r in d["rows"])
    else:
        text = "\n".join(paras)
    if ext == "pdf":
        title = name[: -len(".pdf")]
        try:
            return name, EXT_MIME["pdf"], _pdf_bytes(title, d.get("subtitle") or "", paras), text
        except Exception:  # noqa: BLE001 — 글꼴·PyMuPDF 문제면 텍스트로 대체 / font or PyMuPDF trouble → plain text instead
            logger.warning("가상 지식 에이전트 시드 PDF 생성 실패, 텍스트로 대체: %s", name, exc_info=True)
            body = "\n\n".join([title] + paras)
            return title + ".txt", EXT_MIME["txt"], body.encode("utf-8"), text
    if ext == "xlsx":
        try:
            return name, EXT_MIME["xlsx"], _xlsx_bytes(d["rows"]), text
        except Exception:  # noqa: BLE001 — openpyxl 이 없으면 더미 바이트 / dummy bytes without openpyxl
            return name, EXT_MIME["xlsx"], b"PK\x03\x04" + text.encode("utf-8"), text
    if ext == "hwp":
        return name, EXT_MIME["hwp"], _hwp_dummy(text), text
    return name, EXT_MIME.get(ext, "text/plain"), "\n\n".join(paras).encode("utf-8"), text


# ────────────────────────────────────────────────────────
# 저장 / storage
# ────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mock_kagent_docs(
  tenant TEXT NOT NULL,
  id TEXT NOT NULL,
  folder_id TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  mime TEXT NOT NULL DEFAULT 'application/octet-stream',
  size INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT '',
  content BLOB,
  status TEXT NOT NULL DEFAULT 'done',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(tenant, id)
);
CREATE TABLE IF NOT EXISTS mock_kagent_meta(k TEXT PRIMARY KEY, v TEXT);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> datetime:
    """현재 KST 시각(naive, 테스트가 바꿔 끼운다) / current KST time (naive, patched by tests)"""
    return kst.now()


def _clock() -> float:
    """토큰 만료 판정용 초 단위 시각(테스트가 바꿔 끼운다) / epoch seconds for token expiry (patched by tests)"""
    return time.time()


def _stamp() -> str:
    return _now().isoformat(timespec="seconds")


@contextmanager
def _tx():
    """쓰기 트랜잭션(BEGIN IMMEDIATE) / write transaction (BEGIN IMMEDIATE)"""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rows(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with closing(_conn()) as conn:
        return conn.execute(sql, args).fetchall()


def init_mock_kagent() -> None:
    """테이블 생성(멱등) + 테넌트별 시드 1회 / create the tables (idempotent) and seed each tenant once"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(_conn()) as conn:
        conn.executescript(_SCHEMA)
    for tenant in TENANTS:
        _seed_tenant(tenant)


def _seed_tenant(tenant: str) -> None:
    flag = f"seed_{tenant}_v1"
    if _rows("SELECT 1 FROM mock_kagent_meta WHERE k=?", (flag,)):
        return
    # 원본은 잠금 밖에서 만든다(PDF 생성 시간 동안 DB 쓰기 잠금을 잡지 않게) / build originals before taking the write lock
    payloads = [(d, _seed_payload(tenant, d["id"])) for d in SEED_DOCS[tenant]]
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM mock_kagent_meta WHERE k=?", (flag,)).fetchone():
            return
        for d, (name, mime, content, text) in payloads:
            # INSERT OR IGNORE: 두 서버(8000 · 8010)가 동시에 기동해도 한 벌만 남는다 / two servers booting at once keep one copy
            conn.execute(
                "INSERT OR IGNORE INTO mock_kagent_docs(tenant, id, folder_id, name, mime, size, text, content, status,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,'done',?,?)",
                (tenant, d["id"], d["folder_id"], name, mime, len(content), text[:MAX_TEXT_CHARS], content, d["date"], d["date"]))
        conn.execute("INSERT OR REPLACE INTO mock_kagent_meta(k, v) VALUES(?, '1')", (flag,))


def _status_of(r: sqlite3.Row) -> str:
    """처리 상태 — processing 은 created_at 5초 뒤 done 으로 계산(저장값은 그대로) / processing turns done 5 s after created_at"""
    st = r["status"] or "done"
    if st == "processing":
        try:
            if (_now() - datetime.fromisoformat(r["created_at"])).total_seconds() >= PROCESSING_SEC:
                return "done"
        except ValueError:
            return "done"
    return st


def _public(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "folder_id": r["folder_id"] or "", "size": int(r["size"] or 0),
            "mime": r["mime"], "status": _status_of(r), "updated_at": r["updated_at"]}


# 목록 · 검색은 원본(content BLOB)을 읽지 않는다(2026-09-29) — 큰 업로드가 있으면 목록마다 전부 읽게 된다.
# Listing and search never read the original (content BLOB, 2026-09-29): a large upload would be loaded on every listing.
_LIST_COLS = "id, folder_id, name, mime, size, status, created_at, updated_at"
_SEARCH_COLS = "id, folder_id, name, mime, text, status, created_at"


def list_docs(tenant: str, folder_id: str | None = None) -> list[dict]:
    """문서 목록 — folder_id 없음 = 전체, 있으면 그 폴더 직속 / all documents, or the direct documents of one folder"""
    if folder_id:
        rows = _rows(f"SELECT {_LIST_COLS} FROM mock_kagent_docs WHERE tenant=? AND folder_id=? ORDER BY created_at, id",
                     (tenant, folder_id))
    else:
        rows = _rows(f"SELECT {_LIST_COLS} FROM mock_kagent_docs WHERE tenant=? ORDER BY created_at, id", (tenant,))
    return [_public(r) for r in rows]


def get_doc(tenant: str, doc_id: str) -> sqlite3.Row | None:
    rows = _rows("SELECT * FROM mock_kagent_docs WHERE tenant=? AND id=?", (tenant, doc_id))
    return rows[0] if rows else None


def folder_ids(tenant: str) -> set[str]:
    out: set[str] = set()

    def walk(nodes):
        for n in nodes:
            out.add(n["id"])
            walk(n.get("children") or [])
    walk(FOLDERS.get(tenant) or [])
    return out


def _expand(tenant: str, ids) -> set[str]:
    """폴더 id 목록 → 그 폴더와 하위 폴더 전부 / folder ids → those folders plus every descendant"""
    want = {str(x) for x in ids or [] if isinstance(x, (str, int))}
    out: set[str] = set()

    def walk(nodes, inside: bool):
        for n in nodes:
            hit = inside or n["id"] in want
            if hit:
                out.add(n["id"])
            walk(n.get("children") or [], hit)
    walk(FOLDERS.get(tenant) or [], False)
    return out


def _extract_text(ext: str, data: bytes) -> str:
    """업로드 원본 → 검색용 본문(PDF 는 쪽마다 \\f 로 구분, 텍스트는 그대로, 그 밖은 빈 본문) / uploaded bytes → searchable text"""
    if ext in ("txt", "md"):
        for enc in ("utf-8", "cp949"):
            try:
                return data.decode(enc)[:MAX_TEXT_CHARS]
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
    if ext == "pdf":
        try:
            import fitz
            with fitz.open(stream=data, filetype="pdf") as pdf:
                return "\f".join(p.get_text() for p in pdf).replace("\xa0", " ")[:MAX_TEXT_CHARS]
        except Exception:  # noqa: BLE001 — 깨진 PDF 도 올리기는 된다(이름만 검색) / broken PDFs still upload (name-only search)
            return ""
    return ""


def add_doc(tenant: str, name: str, data: bytes, folder_id: str = "") -> dict:
    """업로드 1건 저장 → processing 레코드 / store one upload → a processing record"""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    # 본문 추출(큰 PDF 는 수 초)은 쓰기 잠금(BEGIN IMMEDIATE) 밖에서 / text extraction (seconds for a big PDF) runs outside the write lock
    text = _extract_text(ext, data)
    now = _stamp()
    doc_id = "doc-" + uuid.uuid4().hex[:10]
    with _tx() as conn:
        conn.execute(
            "INSERT INTO mock_kagent_docs(tenant, id, folder_id, name, mime, size, text, content, status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,'processing',?,?)",
            (tenant, doc_id, folder_id or "", name, EXT_MIME.get(ext, "application/octet-stream"), len(data),
             text, data, now, now))
    rows = _rows(f"SELECT {_LIST_COLS} FROM mock_kagent_docs WHERE tenant=? AND id=?", (tenant, doc_id))
    return _public(rows[0])


def delete_doc(tenant: str, doc_id: str) -> bool:
    with _tx() as conn:
        n = conn.execute("DELETE FROM mock_kagent_docs WHERE tenant=? AND id=?", (tenant, doc_id)).rowcount
    return n > 0


# ────────────────────────────────────────────────────────
# 검색 · 답변 / search and answers
# ────────────────────────────────────────────────────────

_PARTICLES = ("에서는", "으로는", "이라는", "에서", "으로", "까지", "부터", "에게", "처럼", "보다", "이나", "라는", "이란", "마다",
              "은", "는", "이", "가", "을", "를", "에", "의", "로", "와", "과", "도", "만", "요")
# 하다 · 되다 활용 어미(변경하나요 → 변경) / 하다·되다 verb endings (변경하나요 → 변경)
_VERB_ENDINGS = ("하려면", "하나요", "합니까", "할까요", "했나요", "하는지", "합니다", "되나요", "하나", "하는", "하면", "해야",
                 "해요", "할까", "했나", "하기", "한다", "된다", "되나", "되는")
_STOP = {"알려줘", "알려", "주세요", "뭐야", "무엇", "무엇인가", "어떻게", "어떤", "있나", "있어", "해줘", "대해", "대해서",
         "관련", "관한", "내용", "설명", "정리", "문서", "자료"}


def _strip_suffix(word: str, suffixes: tuple) -> str:
    for s in suffixes:
        if word.endswith(s) and len(word) - len(s) >= 2:
            return word[: -len(s)]
    return word


def _terms(query) -> list[str]:
    """질문 → 검색어(조사 · 하다 어미 한 번씩 떼기, 불용어 제외, 2자 이상) / query → search terms (particle and verb ending stripped once)"""
    out: list[str] = []
    for tok in re.findall(r"[0-9A-Za-z가-힣]+", str(query or "").lower()):
        base = _strip_suffix(_strip_suffix(tok, _PARTICLES), _VERB_ENDINGS)
        if base in _STOP or tok in _STOP or (len(base) < 2 and not base.isdigit()):
            continue
        if base not in out:
            out.append(base)
    return out[:12]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\f", " ")).strip()


def _snippet(text: str, terms: list[str], width: int = 120) -> str:
    """첫 검색어 주변 약 120자 발췌 / about 120 characters around the first hit"""
    flat = _flat(text)
    low = flat.lower()
    idx = min((i for i in (low.find(t) for t in terms) if i >= 0), default=-1)
    if idx < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, idx - 40)
    end = min(len(flat), start + width)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")


def _best_sentence(text: str, terms: list[str]) -> str:
    """검색어가 가장 많이 든 문장(최대 160자) — 맞은 검색어 종류 수 › 등장 횟수 › 앞 문장 순
    The sentence holding the most terms (max 160 chars): distinct terms matched, then occurrences, then the earlier one."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", (text or "").replace("\f", "\n")) if s.strip()]
    if not sents:
        return ""

    def rank(p):
        low = p[1].lower()
        return (sum(1 for t in terms if t in low), sum(low.count(t) for t in terms), -p[0])
    best = max(enumerate(sents), key=rank)[1]
    return best if len(best) <= 160 else best[:159] + "…"


def _page_of(text: str, terms: list[str]) -> int:
    low = (text or "").lower()
    idx = min((i for i in (low.find(t) for t in terms) if i >= 0), default=-1)
    return (low[:idx].count("\f") + 1) if idx >= 0 else 1


def search(tenant: str, query, top_k: int = 5, folders=None) -> list[dict]:
    """키워드 점수(이름 3배 + 본문) 상위 문서. 처리 중 문서는 제외. / keyword score (name x3 + body); processing docs are skipped"""
    terms = _terms(query)
    if not terms:
        return []
    allowed = _expand(tenant, folders) if folders else None
    hits = []
    for r in _rows(f"SELECT {_SEARCH_COLS} FROM mock_kagent_docs WHERE tenant=?", (tenant,)):
        if _status_of(r) != "done" or (allowed is not None and (r["folder_id"] or "") not in allowed):
            continue
        name_l, text = r["name"].lower(), r["text"] or ""
        text_l = text.lower()
        raw = sum(3 * name_l.count(t) + text_l.count(t) for t in terms)
        if raw <= 0:
            continue
        hits.append({"doc_id": r["id"], "title": r["name"], "folder_id": r["folder_id"] or "", "raw": raw,
                     "score": round(raw / (raw + 5), 3), "snippet": _snippet(text, terms),
                     "page": _page_of(text, terms) if r["mime"] == EXT_MIME["pdf"] else None,
                     "sentence": _best_sentence(text, terms)})
    hits.sort(key=lambda h: (-h["raw"], h["title"]))
    return hits[: max(1, int(top_k))]


def chat(tenant: str, question, top_k: int = 3, folders=None) -> dict:
    """상위 문서 발췌로 만든 결정적 답변 + 출처 + 모델 표기(외부 LLM 없음) / deterministic answer from top excerpts"""
    hits = search(tenant, question, top_k, folders)
    if not hits:
        answer = "질문과 관련된 문서를 찾지 못했습니다. 다른 표현으로 다시 질문해 주세요."
    else:
        lines = [f"질문과 관련된 사내 문서 {len(hits)}건에서 찾은 내용입니다."]
        for i, h in enumerate(hits, 1):
            title = h["title"].rsplit(".", 1)[0] if "." in h["title"] else h["title"]   # 답변 문장에는 확장자 없이 / no extension in the answer text
            lines.append(f"{i}. 「{title}」: {h['sentence'] or h['snippet']}")
        answer = "\n".join(lines)
    return {"answer": answer,
            "sources": [{"doc_id": h["doc_id"], "title": h["title"], "page": h["page"], "snippet": h["snippet"]} for h in hits],
            "model": TENANTS[tenant]["model"]}


# ────────────────────────────────────────────────────────
# 인증 / auth
# ────────────────────────────────────────────────────────

def _sign(tenant: str, exp: int) -> str:
    return hmac.new(_TOKEN_SIGNING_KEY, f"{tenant}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def issue_token(tenant: str) -> tuple[str, int]:
    """무상태 OAuth 토큰 발급(서명 + 만료) → (토큰, 수명 초) / issue a stateless OAuth token (signature + expiry)"""
    exp = int(_clock()) + TOKEN_TTL
    return f"kat.{tenant}.{exp}.{_sign(tenant, exp)}", TOKEN_TTL


def token_valid(tenant: str, token: str) -> bool:
    parts = str(token or "").split(".")
    if len(parts) != 4 or parts[0] != "kat" or parts[1] != tenant or not parts[2].isdigit():
        return False
    exp = int(parts[2])
    if exp <= _clock():
        return False
    return hmac.compare_digest(parts[3].encode("utf-8"), _sign(tenant, exp).encode("utf-8"))


def authorized(tenant: str, authorization: str | None, api_key: str | None) -> bool:
    """Bearer 데모 키 · X-API-Key 데모 키 · 이 테넌트의 OAuth 토큰 중 하나 / demo bearer key, demo API key or this tenant's token"""
    if api_key and hmac.compare_digest(api_key.strip().encode("utf-8"), DEMO_KEY.encode("utf-8")):
        return True
    if authorization and authorization[:7].lower() == "bearer ":
        tok = authorization[7:].strip()
        if hmac.compare_digest(tok.encode("utf-8"), DEMO_KEY.encode("utf-8")):
            return True
        return token_valid(tenant, tok)
    return False


# ────────────────────────────────────────────────────────
# MCP 도구 · JSON-RPC / MCP tools and JSON-RPC
# ────────────────────────────────────────────────────────

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_FOLDER_IDS = {"type": "array", "items": {"type": "string"}, "description": "검색할 폴더 id 목록(비우면 전체, 하위 폴더 포함)"}

TOOLS: list[dict] = [
    {"name": "kb_chat", "title": "지식 채팅",
     "description": "사내 문서를 검색해 질문에 답하고 답변 근거가 된 출처 문서를 함께 돌려줍니다.",
     "inputSchema": {"type": "object",
                     "properties": {"question": {"type": "string", "description": "사용자 질문", "examples": ["비밀번호 변경 주기는?"]},
                                    "top_k": {"type": "integer", "description": "답변에 쓸 문서 수(1~10)", "default": 3},
                                    "folder_ids": _FOLDER_IDS},
                     "required": ["question"]},
     "outputSchema": {"type": "object",
                      "properties": {"answer": {"type": "string"},
                                     "sources": {"type": "array", "items": {"type": "object", "properties": {
                                         "doc_id": {"type": "string"}, "title": {"type": "string"},
                                         "page": {"type": ["integer", "null"]}, "snippet": {"type": "string"}}}},
                                     "model": {"type": "string"}},
                      "required": ["answer", "sources", "model"]},
     "annotations": {"title": "지식 채팅", **_READ_ONLY}},
    {"name": "kb_search", "title": "지식 검색",
     "description": "사내 문서를 키워드로 검색해 관련 문서와 발췌문을 점수 순으로 돌려줍니다.",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string", "description": "검색어", "examples": ["개인정보 파기"]},
                                    "top_k": {"type": "integer", "description": "돌려줄 문서 수(1~20)", "default": 5},
                                    "folder_ids": _FOLDER_IDS},
                     "required": ["query"]},
     "outputSchema": {"type": "object",
                      "properties": {"hits": {"type": "array", "items": {"type": "object", "properties": {
                          "doc_id": {"type": "string"}, "title": {"type": "string"}, "snippet": {"type": "string"},
                          "score": {"type": "number"}, "folder_id": {"type": "string"}}}}},
                      "required": ["hits"]},
     "annotations": {"title": "지식 검색", **_READ_ONLY}},
    {"name": "kb_get_document", "title": "문서 조회",
     "description": "문서 id 로 문서 1개의 제목과 본문을 돌려줍니다.",
     "inputSchema": {"type": "object",
                     "properties": {"doc_id": {"type": "string", "description": "문서 id", "examples": ["hq-doc-001"]}},
                     "required": ["doc_id"]},
     "outputSchema": {"type": "object",
                      "properties": {"doc_id": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"},
                                     "folder_id": {"type": "string"}},
                      "required": ["doc_id", "title", "text", "folder_id"]},
     "annotations": {"title": "문서 조회", **_READ_ONLY}},
]


class ToolError(Exception):
    pass


def _int_arg(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = args.get(key)
    if v in (None, ""):
        return default
    if isinstance(v, bool):
        raise ToolError(f"{key} 는 정수여야 합니다")
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ToolError(f"{key} 는 정수여야 합니다")
    if not lo <= n <= hi:
        raise ToolError(f"{key} 는 {lo}~{hi} 사이여야 합니다")
    return n


def _folders_arg(args: dict):
    v = args.get("folder_ids")
    if v in (None, "", []):
        return None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ToolError("folder_ids 는 문자열 배열이어야 합니다")
    return v


def _run(tenant: str, name: str, args: dict) -> tuple[str, dict]:
    """도구 실행 → (본문 텍스트, 구조화 결과). 잘못된 입력은 ToolError / run a tool → (text, structured result)"""
    if not isinstance(args, dict):
        raise ToolError("arguments 는 객체여야 합니다")
    if name == "kb_chat":
        q = str(args.get("question") or "").strip()
        if not q:
            raise ToolError("필수 인자 'question' 이 없습니다")
        out = chat(tenant, q, _int_arg(args, "top_k", 3, 1, 10), _folders_arg(args))
        return out["answer"], out
    if name == "kb_search":
        q = str(args.get("query") or "").strip()
        if not q:
            raise ToolError("필수 인자 'query' 가 없습니다")
        hits = search(tenant, q, _int_arg(args, "top_k", 5, 1, 20), _folders_arg(args))
        data = {"hits": [{"doc_id": h["doc_id"], "title": h["title"], "snippet": h["snippet"], "score": h["score"],
                          "folder_id": h["folder_id"]} for h in hits]}
        return f"검색 결과 {len(hits)}건", data
    if name == "kb_get_document":
        doc_id = str(args.get("doc_id") or "").strip()
        if not doc_id:
            raise ToolError("필수 인자 'doc_id' 가 없습니다")
        r = get_doc(tenant, doc_id)
        if r is None:
            raise ToolError(f"문서를 찾을 수 없습니다: {doc_id}")
        text = (r["text"] or "").replace("\f", "\n\n")[:20000]
        return text or r["name"], {"doc_id": r["id"], "title": r["name"], "text": text, "folder_id": r["folder_id"] or ""}
    raise ToolError(f"알 수 없는 도구: {name}")


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(tenant: str, msg, authorization: str | None = None, api_key: str | None = None) -> tuple[int, dict | None]:
    """JSON-RPC 메시지 1건 → (HTTP 상태, 응답 본문 또는 None). 모르는 테넌트 404, 인증 실패 401 + -32001.
    One JSON-RPC message → (HTTP status, body or None). Unknown tenant 404, auth failure 401 + -32001."""
    mid = msg.get("id") if isinstance(msg, dict) else None
    if tenant not in TENANTS:
        return 404, _err(mid, -32004, f"알 수 없는 배포입니다: {tenant}")
    if not authorized(tenant, authorization, api_key):
        return 401, _err(mid, -32001, "유효한 인증 정보가 필요합니다 (Authorization: Bearer 또는 X-API-Key)")
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return 400, _err(mid, -32600, "잘못된 JSON-RPC 요청입니다")
    method, params = msg["method"], msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if mid is None:   # 알림 / notification
        return 202, None
    if method == "initialize":
        want = str(params.get("protocolVersion") or PROTOCOL)
        return 200, {"jsonrpc": "2.0", "id": mid,
                     "result": {"protocolVersion": want if want in SUPPORTED else PROTOCOL,
                                "capabilities": {"tools": {"listChanged": False}},
                                "serverInfo": TENANTS[tenant]["server_info"],
                                "instructions": "가상 고객 배포의 지식 에이전트입니다. 답변은 문서 발췌로 만든 데모 값입니다."}}
    if method == "ping":
        return 200, {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return 200, {"jsonrpc": "2.0", "id": mid, "result": {"tools": copy.deepcopy(TOOLS)}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        if not any(t["name"] == name for t in TOOLS):
            return 200, _err(mid, -32602, f"알 수 없는 도구입니다: {name}")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            text, data = _run(tenant, name, args)
        except ToolError as e:
            return 200, {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
        return 200, {"jsonrpc": "2.0", "id": mid,
                     "result": {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": False}}
    return 200, _err(mid, -32601, f"지원하지 않는 메서드입니다: {method}")


# ────────────────────────────────────────────────────────
# HTTP 라우트 / HTTP routes
# ────────────────────────────────────────────────────────

def _tenant(tenant: str) -> str:
    if tenant not in TENANTS:
        raise MockAPIError(404, "not_found", f"알 수 없는 배포입니다: {tenant}")
    return tenant


def require_auth(tenant: str, authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> None:
    """API 인증 — 데모 Bearer 키 · X-API-Key · OAuth 토큰 / API auth: demo bearer key, X-API-Key or an OAuth token"""
    _tenant(tenant)
    if not authorized(tenant, authorization, x_api_key):
        raise MockAPIError(401, "unauthorized", "유효한 인증 정보가 필요합니다 (Authorization: Bearer 또는 X-API-Key)")


def _disposition(kind: str, name: str) -> str:
    ascii_name = name if name.isascii() and not re.search(r'["\\\r\n]', name) else "document." + name.rsplit(".", 1)[-1]
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def _doc_or_404(tenant: str, doc_id: str) -> sqlite3.Row:
    r = get_doc(tenant, doc_id)
    if r is None:
        raise MockAPIError(404, "not_found", "문서를 찾을 수 없습니다")
    return r


@router.post("/{tenant}/mcp")
async def mcp_endpoint(tenant: str, request: Request, authorization: str | None = Header(None),
                       x_api_key: str | None = Header(None)) -> Response:
    try:
        body = json.loads((await request.body()) or b"null")
    except ValueError:
        return JSONResponse(status_code=400, content=_err(None, -32700, "JSON 파싱 오류"))
    if isinstance(body, list):   # 배치 / batch
        results = [await run_in_threadpool(handle, tenant, m, authorization, x_api_key) for m in body]
        out = [b for _, b in results if b is not None]
        status = max((s for s, _ in results), default=200)
        return JSONResponse(status_code=200 if status < 400 else status, content=out) if out else Response(status_code=202)
    status, out = await run_in_threadpool(handle, tenant, body, authorization, x_api_key)
    if out is None:
        return Response(status_code=status)
    return JSONResponse(status_code=status, content=out)


@router.get("/{tenant}/mcp")
def mcp_get(tenant: str) -> Response:
    """GET 스트림(서버 → 클라이언트 알림)은 제공하지 않는다 / no server-initiated stream"""
    return Response(status_code=405)


@router.delete("/{tenant}/mcp")
def mcp_delete(tenant: str) -> dict:
    return {"ok": True}


@router.post("/{tenant}/oauth/token")
def oauth_token(tenant: str, grant_type: str = Form(""), client_id: str = Form(""), client_secret: str = Form("")) -> Response:
    """OAuth 2.0 client credentials — 오류는 RFC 6749 모양 / OAuth 2.0 client credentials; errors follow RFC 6749"""
    _tenant(tenant)
    if grant_type != "client_credentials":
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type",
                                                      "error_description": "grant_type 은 client_credentials 여야 합니다"})
    ok_id = hmac.compare_digest(client_id.encode("utf-8"), OAUTH_CLIENT_ID.encode("utf-8"))
    ok_secret = hmac.compare_digest(client_secret.encode("utf-8"), OAUTH_CLIENT_SECRET.encode("utf-8"))
    if not (ok_id and ok_secret):
        return JSONResponse(status_code=401, content={"error": "invalid_client", "error_description": "클라이언트 인증에 실패했습니다"})
    token, ttl = issue_token(tenant)
    return JSONResponse(content={"access_token": token, "token_type": "Bearer", "expires_in": ttl},
                        headers={"Cache-Control": "no-store"})


_AUTH = [Depends(require_auth)]


@router.get("/{tenant}/api/v1/health", dependencies=_AUTH)
def health(tenant: str) -> dict:
    return {"status": "ok", "version": "1.0", "capabilities": list(CAPABILITIES)}


@router.get("/{tenant}/api/v1/folders", dependencies=_AUTH)
def folders(tenant: str) -> list:
    return copy.deepcopy(FOLDERS[tenant])


@router.get("/{tenant}/api/v1/documents", dependencies=_AUTH)
def documents(tenant: str, folder_id: str = "") -> list:
    return list_docs(tenant, folder_id.strip() or None)


@router.post("/{tenant}/api/v1/documents", status_code=201, dependencies=_AUTH)
def doc_upload(tenant: str, file: UploadFile = File(...), folder_id: str = Form("")) -> dict:
    name = Path(unicodedata.normalize("NFC", file.filename or "")).name.strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not name or ext not in EXT_MIME:
        raise MockAPIError(422, "unsupported_type", "지원하지 않는 파일 형식입니다")
    fid = (folder_id or "").strip()
    if fid and fid not in folder_ids(tenant):
        raise MockAPIError(422, "folder_not_found", "존재하지 않는 폴더입니다")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise MockAPIError(413, "too_large", "파일이 너무 큽니다")
    if not data:
        raise MockAPIError(422, "empty", "빈 파일입니다")
    return add_doc(tenant, name, data, fid)


@router.get("/{tenant}/api/v1/documents/{doc_id}/status", dependencies=_AUTH)
def doc_status(tenant: str, doc_id: str) -> dict:
    st = _status_of(_doc_or_404(tenant, doc_id))
    return {"status": st, "message": "처리가 끝났습니다" if st == "done" else "문서를 처리하고 있습니다"}


@router.get("/{tenant}/api/v1/documents/{doc_id}/preview", dependencies=_AUTH)
def doc_preview(tenant: str, doc_id: str) -> Response:
    r = _doc_or_404(tenant, doc_id)
    if r["mime"] == EXT_MIME["pdf"]:
        return Response(content=bytes(r["content"] or b""), media_type="application/pdf",
                        headers={"Content-Disposition": _disposition("inline", r["name"])})
    if r["mime"] in TEXT_MIMES:
        return Response(content=bytes(r["content"] or b""), media_type="text/plain; charset=utf-8")
    raise MockAPIError(415, "unsupported_media_type", "미리보기를 지원하지 않는 형식입니다")


@router.get("/{tenant}/api/v1/documents/{doc_id}/download", dependencies=_AUTH)
def doc_download(tenant: str, doc_id: str) -> Response:
    r = _doc_or_404(tenant, doc_id)
    return Response(content=bytes(r["content"] or b""), media_type=r["mime"] or "application/octet-stream",
                    headers={"Content-Disposition": _disposition("attachment", r["name"])})


@router.delete("/{tenant}/api/v1/documents/{doc_id}", dependencies=_AUTH)
def doc_delete(tenant: str, doc_id: str) -> dict:
    if not delete_doc(tenant, doc_id):
        raise MockAPIError(404, "not_found", "문서를 찾을 수 없습니다")
    return {"ok": True}
