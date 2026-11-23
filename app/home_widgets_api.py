"""홈 대시보드 · 위젯 에이전트 API(2026-11-13 1단계, 2026-11-16 위젯 에이전트, 계약 = docs/widget-agent.md 5절). 저장 · 계산은
app/home_widgets.py, 대화 한 턴은 app/widget_agent.py.

  GET    /api/home/dashboard?acting_user_id=               {layout_options, config(+ saved), widgets(기본 9개 + 내 위젯, 위젯마다 size)}
  PUT    /api/home/dashboard                               {acting_user_id, layout_type, items(격자) | columns(옛 세 열)} → 저장된 config
  GET    /api/home/widgets?acting_user_id=                 {widgets} 내 위젯만
  POST   /api/home/widgets                                 {acting_user_id, spec} → 위젯(배치 편집의 위젯 추가 서랍에 생긴다)
  PUT    /api/home/widgets/{key}                           {acting_user_id, spec} → 위젯(정의 바꾸기)
  DELETE /api/home/widgets/{key}?acting_user_id=           {ok, config} 저장된 배치에서도 그 키를 뺀다
  GET    /api/home/widgets/{key}/data?acting_user_id=      {key, model, fetched_at} 지금 데이터로 다시 계산
  POST   /api/home/agent/turn                              {acting_user_id, widget, messages, message} → {widget, model, reply, trace, ask}
  POST   /api/home/agent/turn/stream                       같은 본문(+ source: auto · internal · data · docs · web) → 이벤트 스트림 plan · stage · branch · picked · round · tool · draft ·
                                                           done(또는 error). 화면이 스트림을 끊으면(멈추기) 턴은 다음 라운드 · 도구 앞에서 멈춘다
  GET    /api/home/agent/tools                             {tree} 위젯 에이전트에 붙은 도구(에이전트 › 묶음 › 도구)
  GET    /api/home/agent/chat/{key}?acting_user_id=        {key, chat | null, updated_at} 그 위젯의 대화 저장본(2026-11-19)
  PUT    /api/home/agent/chat/{key}                        {acting_user_id, chat} → {key, updated_at}
  POST   /api/home/agent/model                             {acting_user_id, widget} → {widget, model} 작업본의 표시 모델(변경 기록 미리보기)
  POST   /api/home/agent/refresh                           {acting_user_id, widget} → {changed, widget?, model?, fetched_at} 작업본의 출처를 지금 다시

신원 = acting_user_id 의 앞뒤 공백을 뺀 값(빈 문자열 = 데모 기본 사용자). GET · DELETE 는 쿼리, PUT · POST 는 본문.
오류: 정의 · 배치 · 개수 상한 · 틀린 신원 422(detail = 사용자에게 보일 문장), 없는 위젯 · 남의 위젯 404, 기본 위젯 삭제 400.
위젯 에이전트 턴은 작업본을 서버에 두지 않는다(화면이 작업본 · 대화를 보낸다): 빈 요청 · 틀린 작업본 422, 모델 실패 503.
데이터 가져오기(3단계, app/widget_data.py)는 신원의 권한 안에서만 사내 데이터 · 문서를 찾는다. GET …/data 는 출처가 있는 부분의 내용을 때가
되면 다시 가져온다(사내 데이터 1분 · 문서 6시간 · 웹 30분) — 20초 넘게 걸리면 예전 내용으로 답하고 뒤에서 마저 저장하며, 아무것도 못 가져왔으면
그 위젯은 10분 쉰다.
GET /api/home/dashboard 의 만든 위젯에는 정의(spec)가 없다(모델만) — 정의는 GET /api/home/widgets 가 준다.

Home dashboard API (2026-11-13, widget agent phase 1; contract = docs/widget-agent.md section 5). Storage and computing
live in app/home_widgets.py. The identity is acting_user_id stripped (the empty string is the demo default user): a
query parameter for GET and DELETE, a body field for PUT and POST. Errors: definition, layout and cap errors are 422
(detail is a user-facing sentence), as is a bad identity; a missing or foreign widget is 404 and deleting a built-in
is 400. Made widgets in GET /api/home/dashboard carry the model without the definition (spec); GET /api/home/widgets
returns the definitions. A widget-agent turn keeps no working copy on the server (the screen sends the draft and the
conversation): an empty request or a wrong draft is 422 and a model failure is 503. Fetching (phase 3, app/widget_data.py) finds
company data and documents within the identity's permissions only. GET …/data fetches a part's content again when due
(company data 1 minute, documents 6 hours, the web 30 minutes); past 20 seconds it answers with the old content and stores the
new one in the background, and a widget that got nothing back rests for 10 minutes.
"""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import json
import logging
import queue
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import access, home_widgets, kst, widget_agent, widget_data

logger = logging.getLogger("ai365.home_widgets_api")

router = APIRouter(prefix="/api/home", tags=["home"])

# 사용자 입력 오류 = 422 / user input errors = 422
_INPUT_ERRORS = (home_widgets.SpecError, home_widgets.ConfigError, home_widgets.WidgetError)
NOT_FOUND = "존재하지 않는 위젯입니다"


# 본문 항목은 형식을 가리지 않고 받는다: 틀린 형식(spec: null, layout_type: 5 …)도 저장소의 정규화가 사용자 문장으로 거절한다
# (pydantic 의 영어 오류 목록 대신 계약의 "detail = 사용자에게 보일 문장").
# Body fields are accepted untyped: a wrong shape (spec: null, layout_type: 5, …) is refused by the store's normalization
# with a user sentence, as the contract says, instead of pydantic's English error list.
class DashIn(BaseModel):
    acting_user_id: Any = ""
    layout_type: Any = ""
    items: Any = None     # 4단계 격자 [{widget_key, x, y, w, h}] / the phase-4 grid
    columns: Any = None   # 옛 세 열 형식(받으면 격자로 바꾼다) / the older three-column shape (converted to a grid)


class WidgetIn(BaseModel):
    acting_user_id: Any = ""
    spec: Any = None


class TurnIn(BaseModel):
    acting_user_id: Any = ""  # 데이터 가져오기의 권한 범위 / the permission scope of fetching
    widget: Any = None        # 작업본(None = 새 위젯) / the draft (None = a new widget)
    messages: Any = None      # 대화 기록 [{role, text, trace}] / the conversation so far
    message: Any = ""
    source: Any = None        # 가져올 곳(입력 카드의 [자동 ▾]: None · auto · internal · data · docs · web, 2026-11-19) / the place picked in the input card


class ChatIn(BaseModel):
    acting_user_id: Any = ""
    chat: Any = None


class DraftIn(BaseModel):
    acting_user_id: Any = ""
    widget: Any = None


AGENT_DOWN = "위젯 에이전트가 지금 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요"
MAX_OWNER = 64   # acting_user_id 길이 / length of acting_user_id


def _owner(acting_user_id) -> str:
    """신원: 글자나 정수만, 앞뒤 공백을 뺀 MAX_OWNER 자 이하. 그 밖은 422.
    The identity: text or an integer only, stripped and at most MAX_OWNER characters; anything else is a 422."""
    if acting_user_id is None:
        return ""
    if isinstance(acting_user_id, bool) or not isinstance(acting_user_id, (str, int)):
        raise HTTPException(status_code=422, detail="사용자 식별자가 올바르지 않습니다")
    owner = str(acting_user_id).strip()
    if len(owner) > MAX_OWNER:
        raise HTTPException(status_code=422, detail="사용자 식별자가 올바르지 않습니다")
    return owner


@router.get("/dashboard")
def get_dashboard(acting_user_id: str = "") -> dict:
    return home_widgets.get_dashboard(_owner(acting_user_id))


@router.put("/dashboard")
def put_dashboard(body: DashIn) -> dict:
    try:
        raw = {"layout_type": body.layout_type, "items": body.items} if body.items is not None or body.columns is None             else {"layout_type": body.layout_type, "columns": body.columns}
        return home_widgets.save_dashboard(_owner(body.acting_user_id), raw)
    except _INPUT_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/widgets")
def list_widgets(acting_user_id: str = "") -> dict:
    return {"widgets": home_widgets.list_widgets(_owner(acting_user_id))}


@router.post("/widgets")
def create_widget(body: WidgetIn) -> dict:
    try:
        return home_widgets.create_widget(_owner(body.acting_user_id), body.spec)
    except _INPUT_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/widgets/{key}")
def update_widget(key: str, body: WidgetIn) -> dict:
    try:
        widget = home_widgets.update_widget(_owner(body.acting_user_id), key, body.spec)
    except _INPUT_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if widget is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return widget


@router.delete("/widgets/{key}")
def delete_widget(key: str, acting_user_id: str = "") -> dict:
    owner = _owner(acting_user_id)
    if key in home_widgets.BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail="기본 위젯은 삭제할 수 없습니다")
    if not home_widgets.delete_widget(owner, key):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return {"ok": True, "config": home_widgets.get_dashboard(owner)["config"]}


_refreshing: set[str] = set()
_refreshing_lock = threading.Lock()
_rested: dict[str, float] = {}       # 다시 가져오기에 실패한 위젯 → 시각(monotonic) / widgets whose refresh got nothing → when
REST_SEC = 600                       # 실패한 위젯은 10분 쉰다(홈을 열 때마다 모델을 부르지 않게) / a failed widget rests 10 minutes
_REFRESH_POOL = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="widget-refresh")


def _claim(key: str) -> bool:
    """이 위젯을 지금 다시 가져오는 요청이 없고 쉬는 중도 아니면 맡는다 / takes the refresh unless another request has it or it rests"""
    with _refreshing_lock:
        if key in _refreshing or time.monotonic() - _rested.get(key, -1e9) < REST_SEC:
            return False
        _refreshing.add(key)
        return True


def _release(key: str) -> None:
    with _refreshing_lock:
        _refreshing.discard(key)


def _refresh_job(owner: str, key: str, widget: dict) -> dict | None:
    """때가 된 부분을 다시 가져와 저장 → 새 모델(못 가져왔거나 그 사이 정의가 바뀌었으면 None). 기다리는 요청이 먼저 끝나도 끝까지 한다.
    Refreshes the due parts and stores them → the new model (None when nothing came back or the definition changed meanwhile);
    it runs to the end even after the waiting request has answered."""
    try:
        fresh = widget_data.refresh(widget["spec"], access.resolve_eff(owner))
        if fresh is None:
            with _refreshing_lock:
                _rested[key] = time.monotonic()
            return None
        return home_widgets.store_refresh(owner, key, fresh, widget)
    except Exception as exc:  # noqa: BLE001 — 다시 가져오기 실패는 예전 내용으로 / a failed refresh keeps the old content
        logger.warning("위젯 내용 다시 가져오기 실패: %s", type(exc).__name__)
        with _refreshing_lock:
            _rested[key] = time.monotonic()
        return None
    finally:
        _release(key)


@router.get("/widgets/{key}/data")
def widget_data_route(key: str, acting_user_id: str = "") -> dict:
    """지금 데이터로 다시 계산. 출처가 있고 때가 됐으면 먼저 내용을 다시 가져온다(신원의 권한 안에서) / recompute; fetch again first when due"""
    owner = _owner(acting_user_id)
    widget = home_widgets.get_widget(owner, key)
    if widget is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    spec = widget["spec"] if isinstance(widget["spec"], dict) else {}
    # 때가 된 부분이 있을 때만 권한을 읽고 가져온다. 같은 위젯을 동시에 두 번 가져오지 않고(홈 · 미리보기가 함께 열려도 모델 호출은 한 번),
    # REFRESH_WAIT 초까지만 기다린다(넘으면 예전 내용으로 답하고 일은 뒤에서 마쳐 저장한다)
    # permissions are read and content fetched only when a part is due, never twice at once for one widget, and the request waits
    # REFRESH_WAIT seconds at most (then the old content answers while the job finishes and stores in the background)
    if widget_data.due(spec) and _claim(key):
        job = _REFRESH_POOL.submit(_refresh_job, owner, key, widget)
        try:
            model = job.result(timeout=widget_data.REFRESH_WAIT)
        except cf.TimeoutError:
            model = None
        if model is not None:
            return {"key": key, "model": model, "fetched_at": kst.now_iso()}
    try:
        data = home_widgets.widget_data(owner, key)
    except _INPUT_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if data is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return data


def _source(value) -> str | None:
    """가져올 곳: 없음 · '' · auto = 에이전트가 고른다(None), internal = 사내 데이터 · 사내 문서(웹 없이), data · docs · web 은 그곳만. 그 밖은 422.
    The place to fetch from: none, '' or auto lets the agent decide (None); internal = company data and documents (no web); data, docs
    or web only there; anything else is a 422."""
    if value in (None, "", "auto"):
        return None
    if isinstance(value, str) and value in widget_agent.SCOPE_SOURCES:
        return value
    raise HTTPException(status_code=422, detail="데이터를 가져올 곳이 올바르지 않습니다")


def _turn_input(body: TurnIn) -> tuple[str, str]:
    """턴 본문 검사: (신원, 요청). 빈 요청 · 너무 긴 요청 · 틀린 작업본은 422 / checks a turn body: (owner, message)"""
    owner = _owner(body.acting_user_id)
    message = body.message.strip() if isinstance(body.message, str) else ""
    if not message:
        raise HTTPException(status_code=422, detail="요청 내용을 입력해 주세요")
    if len(message) > widget_agent.MAX_MESSAGE:
        raise HTTPException(status_code=422, detail=f"요청은 {widget_agent.MAX_MESSAGE}자까지 쓸 수 있습니다")
    try:   # 작업본은 스트림을 열기 전에 검사한다(틀리면 422 문장) / the draft is checked before any stream opens
        home_widgets.normalize_spec(body.widget if body.widget is not None else {"v": home_widgets.SPEC_VERSION}, draft=True)
    except home_widgets.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return owner, message


@router.post("/agent/turn")
def agent_turn(body: TurnIn) -> dict:
    """위젯 에이전트 한 턴(작업본은 화면이 들고 있다) / one widget-agent turn (the screen holds the draft)"""
    owner, message = _turn_input(body)
    source = _source(body.source)
    try:
        return widget_agent.run_turn(body.widget, body.messages, message, eff=access.resolve_eff(owner), owner=owner, source=source)
    except home_widgets.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 모델 · 키 장애는 한 문장으로 / model or key trouble becomes one sentence
        logger.warning("위젯 에이전트 턴 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail=AGENT_DOWN) from exc


STREAM_POLL = 0.5   # 화면이 끊었는지 확인하는 간격(초) / how often a disconnect is checked (s)


@router.post("/agent/turn/stream")
def agent_turn_stream(body: TurnIn, request: Request) -> StreamingResponse:
    """한 턴을 이벤트 스트림으로: plan(찾을 곳 · 모양) · stage(갈래 시작) · branch(갈래 결과) · picked(쓴 갈래) · round(라운드마다 고른 도구) ·
    tool(도구 결과) · draft(미리 그린 위젯 — 의도 판단이 끝나면 제목 · 칸 모양) · done(턴 결과) 또는 error. 화면이 스트림을 끊으면(멈추기,
    2026-11-19) 턴은 다음 라운드 · 도구 앞에서 멈추고 아무것도 보내지 않는다(이미 시작한 모델 호출은 끝까지 간다).
    One turn as an event stream: plan, stage, branch, picked, round, tool, draft (the widget drawn early), done or error. When the
    screen drops the stream (stop, 2026-11-19) the turn halts before its next round or tool and sends nothing more (a model call
    already under way runs to its end)."""
    owner, message = _turn_input(body)
    source = _source(body.source)
    eff = access.resolve_eff(owner)
    events: queue.Queue = queue.Queue()
    stop = threading.Event()

    def emit(kind: str, data: dict) -> None:
        events.put((kind, data))

    def work() -> None:
        try:
            events.put(("done", widget_agent.run_turn(body.widget, body.messages, message, eff=eff, emit=emit, owner=owner,
                                                      source=source, cancel=stop.is_set)))
        except widget_data.Cancelled:   # 화면이 멈췄다 — 보낼 곳이 없다 / the screen stopped; nobody is listening
            logger.info("위젯 에이전트 턴을 화면이 멈췄습니다 / the screen stopped a widget-agent turn")
        except home_widgets.SpecError as exc:
            events.put(("error", {"status": 422, "detail": str(exc)}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("위젯 에이전트 스트림 턴 실패: %s", type(exc).__name__)
            events.put(("error", {"status": 503, "detail": AGENT_DOWN}))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True, name="widget-agent-turn").start()

    async def stream():
        # 화면이 끊으면(멈추기 · 다른 화면) 턴도 멈춘다: 끊김을 STREAM_POLL 초마다 확인하고(이벤트가 이어서 와도 — ASGI 2.4 서버는 Starlette 가
        # 끊김을 따로 듣지 않는다, 독립 검토), 응답이 취소 · 종료돼도 finally 에서 멈춤을 건다
        # a dropped stream (stop, another screen) stops the turn: disconnects are checked every STREAM_POLL seconds, even while events keep
        # coming (on ASGI 2.4 servers Starlette does not listen for them, independent review), and a cancelled or closed response sets the stop
        last = time.monotonic()
        try:
            while True:
                try:
                    item = await asyncio.to_thread(events.get, True, STREAM_POLL)
                except queue.Empty:
                    item = False
                if time.monotonic() - last >= STREAM_POLL:
                    last = time.monotonic()
                    if await request.is_disconnected():
                        return
                if item is False:
                    continue
                if item is None:
                    return
                kind, data = item
                yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            stop.set()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/agent/tools")
def agent_tools() -> dict:
    return {"tree": widget_agent.tool_tree()}


# ────────────────────────────────────────────────────────
# 대화 저장 · 변경 기록 미리보기 · 지금 새로 가져오기(2026-11-19, 문서 13절)
# the saved conversation, history previews and refreshing now (2026-11-19, section 13)
# ────────────────────────────────────────────────────────

@router.get("/agent/chat/{key}")
def get_agent_chat(key: str, acting_user_id: str = "") -> dict:
    """그 위젯의 대화 저장본(없으면 chat = null). 없거나 남의 위젯이면 404 / the widget's saved conversation; 404 when missing or foreign"""
    chat = home_widgets.get_chat(_owner(acting_user_id), key)
    if chat is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return chat


@router.put("/agent/chat/{key}")
def put_agent_chat(key: str, body: ChatIn) -> dict:
    """대화 저장(덮어쓰기). 틀리거나 너무 큰 저장본 422, 없거나 남의 위젯 404 / saves the conversation; 422 when wrong or too large, 404 when missing"""
    try:
        out = home_widgets.save_chat(_owner(body.acting_user_id), key, body.chat)
    except _INPUT_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if out is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return out


@router.post("/agent/model")
def agent_model(body: DraftIn) -> dict:
    """작업본 → {widget(정규화), model} — 변경 기록의 지난 모습을 미리 보거나 되돌릴 때(모델 호출 없음). 틀리면 422.
    A draft → {widget (normalized), model}, for previewing or restoring a history state (no model call); 422 when wrong."""
    _owner(body.acting_user_id)
    try:
        clean = home_widgets.normalize_spec(body.widget, draft=True)
    except home_widgets.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"widget": clean, "model": home_widgets.model_of(clean)}


AGENT_REFRESH_WAIT = 120   # [지금 새로 가져오기]가 기다리는 시간(초) / how long refreshing now may take (s)
REFRESH_SLOW = "새로 가져오기가 오래 걸려 멈췄습니다. 잠시 뒤 다시 시도해 주세요"
REFRESH_DOWN = "지금은 새로 가져올 수 없습니다. 잠시 뒤 다시 시도해 주세요"


@router.post("/agent/refresh")
def agent_refresh(body: DraftIn) -> dict:
    """작업본의 출처를 때와 상관없이 지금 다시 가져온다(신원의 권한 안에서, 저장하지 않는다 — 화면이 작업본으로 받는다). 사내 데이터는 서버가 서명한
    SQL 만 다시 실행한다(서명이 맞지 않는 SQL 은 버린다). → {changed, widget, model, fetched_at}(바뀐 것이 없으면 changed False 만).
    Fetches the draft's origins again now, due or not (within the identity's permissions; nothing is stored, the screen takes it as
    its draft). Only server-signed SQL is re-run (unsigned SQL is dropped). → {changed, widget, model, fetched_at}."""
    owner = _owner(body.acting_user_id)
    try:
        clean = home_widgets.normalize_spec(body.widget, draft=True)
    except home_widgets.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    clean["origins"] = home_widgets._trusted(owner, clean["origins"])  # noqa: SLF001 — 화면이 보낸 SQL 은 서명이 맞을 때만 / screen-sent SQL only when signed
    try:
        fresh = widget_data.bounded(lambda: widget_data.refresh(clean, access.resolve_eff(owner), force=True), AGENT_REFRESH_WAIT)
    except cf.TimeoutError as exc:
        raise HTTPException(status_code=504, detail=REFRESH_SLOW) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("위젯 작업본 새로 가져오기 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail=REFRESH_DOWN) from exc
    if fresh is None:
        return {"changed": False, "fetched_at": kst.now_iso()}
    try:
        new = home_widgets.normalize_spec(fresh, draft=True)
    except home_widgets.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"changed": True, "widget": new, "model": home_widgets.model_of(new), "fetched_at": kst.now_iso()}
