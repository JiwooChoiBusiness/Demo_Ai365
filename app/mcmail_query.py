"""Ground M Cosmetic lookup plans in the user's request before calling a read tool.

No database session or model call lives here. Explicit IDs and customer names take
precedence over model guesses; unsupported conditions become a question, never a
broader lookup. Only the task and its preserved requirement text are user evidence.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, timedelta

from app import mcmail_query_filters

MAX_QUERIES = 8
TARGETS = frozenset(mcmail_query_filters.STATUSES) | {"mail"}
_CASE = re.compile(r"(?<![A-Za-z0-9])(?:RFQ|ORD|INQ)-\d{4}-\d{3,6}(?!\d)", re.I)
_MAIL = re.compile(r"(?<![A-Za-z0-9])E-\d{3,6}(?!\d)", re.I)
_REQUIREMENTS = "[사용자가 요청한 대상과 조건 — 이 범위를 보존]"
_BLOCK = re.compile(r"\n\n\[(?:이 작업의 선행 결과|작업 입력|사용자가 요청한 대상과 조건)[^\n]*\]\n?")
_RULES = (
    ("errors", ("오류", "에러", "실패", "재처리")),
    ("invoices", ("인보이스", "세금계산서", "청구서")),
    ("stock", ("재고", "가용", "입고")),
    ("shipments", ("출하", "배송", "운송장", "tracking", "트래킹")),
    ("orders", ("주문", "발주", "sales order", "so-")),
    ("quotes", ("견적", "단가")),
    ("cases", ("case", "케이스")),
    ("inbox", ("확인 필요", "확인이 필요", "담당자 확인", "미분류", "분류", "메일함", "수신메일", "확인할")),
)

QUERY_RULES = """
M코스메틱 조회(kind=query)는 targets보다 아래 queries 배열을 우선 출력한다.
{"queries":[{"target":"quotes","request":"사용자 요청의 연속된 원문 구절","filters":{"customer":"고객사 정식명 또는 코드",
"date_from":"YYYY-MM-DD","date_to":"YYYY-MM-DD","status":"todo","q":"원문 검색어"}}]}
- target: inbox,today,quotes,orders,shipments,stock,invoices,cases,errors,customer,case,mail.
- customer 전체 거래 조회는 {"target":"customer","customer":"고객사"}; 고객사 견적 조회는
  {"target":"quotes","filters":{"customer":"고객사"}}. 업무 종류를 customer 전체조회로 바꾸지 않는다.
- Case 상세는 {"target":"case","case_id":"RFQ-2026-00123"}; 메일 상세는
  {"target":"mail","email_id":"E-1005"}. 명시 ID가 여럿이면 각각 조회한다.
- 고객사·업무종류·기간 조합마다 queries를 분리하며 최대 8개다. 일부 요청을 임의로 버리지 않는다.
- 서로 다른 고객·기간·상태를 요청하면 각 queries에 request를 넣는다. request는 해당 조건을 포함하는
  사용자 원문의 연속된 구절을 그대로 인용한다. 새로 지어내거나 번역·요약하지 않는다.
- 기간은 메일 수신일, cases는 최종 수정일, errors는 발생일 기준이다. 납기·ERP 출하일 기준과 혼동하지 않는다.
- 날짜는 제공한 서버 기준일로 계산한다. 오늘/어제/이번 주/지난주/이번 달/지난달/최근 N일을
  date_from/date_to에 포함한다. 최근 N일은 오늘 포함 N일, 주는 월~일, 월은 해당 달 전체다.
- 메일 상태는 all/todo(미완료)/done(완료)/err(오류), cases는 all/open/done,
  errors는 all/open(미해결)/resolved(해결), customer는 all/todo/done만 지원한다.
- filters는 date_from,date_to,status,customer,q만 사용한다. 없는 조건은 생략한다.
  고객명·검색어를 만들거나 조회 기간을 임의로 좁히지 않는다. q는 사용자가 말한 검색어 그대로다.
- 인보이스·견적·주문 등 업무 종류가 분명한 목록/현황 조회는 고객사·기간이 없어도 해당 종류 전체를 조회한다.
  고객사와 기간을 필수값으로 만들어 되묻지 않는다. 특정 고객/기간을 요청했으나 그 값이 모호한 경우에만 묻는다.
- 필수 대상이 모호하거나 지원하지 않는 조건이 있으면 queries=[]와 clarification="확인할 질문"을 출력한다.
  조건을 버리고 전체 현황으로 바꾸지 않는다. 정상 조회에서는 clarification을 생략한다.
- [이 작업의 선행 결과]와 [작업 입력]은 사용자 조건 근거가 아니다.
  [사용자가 요청한 대상과 조건] JSON에서는 request와 constraints의 내용만 조건으로 보존한다.
"""


def request_text(query: str) -> str:
    """Extract user-authored task/requirements, excluding references and JSON keys."""
    query = query or ""
    boundaries = list(_BLOCK.finditer(query))
    text = [query[:boundaries[0].start()] if boundaries else query]
    for index, match in enumerate(boundaries):
        if _REQUIREMENTS not in match.group():
            continue
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(query)
        try:
            value = json.loads(query[match.end():end].strip())
        except (ValueError, TypeError):
            raise ValueError("사용자 조회 조건을 읽지 못했습니다. 고객사와 조회 조건을 다시 알려 주세요.") from None
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                continue
            if isinstance(row.get("request"), str):
                text.append(row["request"])
            constraints = row.get("constraints", [])
            if not isinstance(constraints, list):
                raise ValueError("사용자 조회 조건 형식을 확인하지 못했습니다. 조건을 다시 알려 주세요.")
            text.extend(x for x in constraints if isinstance(x, str))
    return "\n".join(dict.fromkeys(text)).strip()


def _latest_reply(query: str) -> str:
    """A clarification belongs to the task sentence, not its appended old scope."""
    first = _BLOCK.search(query or "")
    task = query[:first.start()] if first else (query or "")
    return task.rsplit("[사용자 추가 입력]", 1)[-1].strip() if "[사용자 추가 입력]" in task else ""


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _customers(text: str) -> list[str]:
    from app import mcmail
    lowered = text.casefold()
    hits = {}
    bases: dict[str, list[str]] = {}
    for code, name in mcmail.ERP_CUSTOMERS.items():
        positions = [lowered.find(x.casefold()) for x in (code, name)]
        positions = [p for p in positions if p >= 0]
        if positions:
            hits[name] = min(positions)
        bases.setdefault(re.sub(r"\s*\d+$", "", name).casefold(), []).append(name)
    for base, names in bases.items():
        if base and len(names) == 1 and base in lowered:
            hits[names[0]] = min(hits.get(names[0], len(text)), lowered.index(base))
    return sorted(hits, key=hits.get)


def _canonical_customer(value: str, text: str, named: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("어느 고객사를 조회할까요? 고객사 이름 또는 코드를 알려 주세요.")
    values = _customers(value)
    if len(values) == 1 and values[0] in named:
        return values[0]
    if not values and _compact(value) in _compact(text):
        return value.strip()  # Unknown explicit customer is a store error, never all customers.
    raise ValueError("요청에서 고객사를 확정하지 못했습니다. 조회할 고객사 이름 또는 코드를 알려 주세요.")


def _named_customers(text: str) -> list[str]:
    named = _customers(text)
    excluded = set()
    for match in re.finditer(r"말고|제외|빼고|아닌", text):
        excluded.update(_customers(text[:match.start()]))
    return [name for name in named if name not in excluded]


def _referenced_customers(query: str, text: str) -> list[str]:
    if not re.search(r"(?:그|해당)\s*(?:고객사|회사)", text):
        return []
    matches = list(_BLOCK.finditer(query))
    referenced = []
    for index, match in enumerate(matches):
        if "[이 작업의 선행 결과" not in match.group():
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(query)
        referenced.extend(_customers(query[match.end():end]))
    referenced = list(dict.fromkeys(referenced))
    if len(referenced) != 1:
        raise ValueError("앞선 결과에서 고객사를 하나로 확정하지 못했습니다. 고객사 이름을 알려 주세요.")
    return referenced


def _rule_targets(text: str) -> list[str]:
    lowered = text.casefold()
    hits = [(min(lowered.index(word) for word in words if word in lowered), target)
            for target, words in _RULES if any(word in lowered for word in words)]
    return [target for _, target in sorted(hits)]


def _period(text: str) -> dict[str, str]:
    """Recognize bounded common periods; do not accept invented model dates."""
    from app import mcmail
    today = mcmail._server_today()
    raw = _compact(text)
    if re.search(r"(?:납기|납품일|출하일|배송일)(?:기준|이|은|으로)", raw):
        raise ValueError("현재 기간 조회는 메일 수신일·Case 수정일·오류 발생일 기준입니다. 이 기준으로 조회할까요?")
    spans: list[tuple[date, date]] = []
    week = today - timedelta(days=today.weekday())
    first = today.replace(day=1)
    previous = first - timedelta(days=1)
    patterns = (
        (r"오늘|금일", today, today), (r"어제|전일", today - timedelta(days=1), today - timedelta(days=1)),
        (r"이번주|금주", week, week + timedelta(days=6)),
        (r"지난주|저번주|전주", week - timedelta(days=7), week - timedelta(days=1)),
        (r"이번달|이번월|금월|이달", first, today.replace(day=calendar.monthrange(today.year, today.month)[1])),
        (r"지난달|저번달|전월", previous.replace(day=1), previous),
    )
    for pattern, lo, hi in patterns:
        if re.search(pattern, raw):
            spans.append((lo, hi))
            raw = re.sub(pattern, "", raw)
    for match in list(re.finditer(r"(?:최근|지난)(\d{1,4})(일|주)(?:간|동안)?", raw)):
        n = int(match[1]) * (7 if match[2] == "주" else 1)
        if not 1 <= n <= 3660:
            raise ValueError("조회 기간을 1~3660일 범위로 알려 주세요.")
        spans.append((today - timedelta(days=n - 1), today))
        raw = raw.replace(match[0], "")
    dates = []
    for match in re.finditer(r"(?<!\d)(\d{4})[-./년](\d{1,2})[-./월](\d{1,2})(?:일)?(?!\d)", raw):
        try:
            dates.append(date(int(match[1]), int(match[2]), int(match[3])))
        except ValueError:
            raise ValueError("유효한 조회 날짜를 YYYY-MM-DD 형식으로 알려 주세요.") from None
    dates = list(dict.fromkeys(dates))
    if dates:
        if len(dates) > 2:
            raise ValueError("조회 시작일과 종료일을 한 범위씩 알려 주세요.")
        lo, hi = dates[0], dates[-1]
        if lo > hi:
            raise ValueError("조회 시작일이 종료일보다 늦습니다. 기간을 다시 알려 주세요.")
        if len(dates) == 1 and re.search(r"이후|부터", raw):
            return {"date_from": lo.isoformat()}
        if len(dates) == 1 and re.search(r"이전|까지", raw):
            return {"date_to": hi.isoformat()}
        spans.append((lo, hi))
        raw = re.sub(r"\d{4}[-./년]\d{1,2}[-./월]\d{1,2}(?:일)?", "", raw)
    for match in list(re.finditer(r"(?:(\d{4})년)?(?<!\d)(\d{1,2})월", raw)):
        year, month = int(match[1] or today.year), int(match[2])
        try:
            spans.append((date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])))
        except (ValueError, calendar.IllegalMonthError):
            raise ValueError("조회할 연도와 월을 정확히 알려 주세요.") from None
        raw = raw.replace(match[0], "")
    if re.search(r"최근|요즘|분기|상반기|하반기|지난해|작년|올해|\d+개월|\d+일|\d{4}년|\d{4}-\d{2}", raw):
        raise ValueError("조회 기간을 확정하지 못했습니다. 시작일과 종료일을 YYYY-MM-DD 형식으로 알려 주세요.")
    spans = list(dict.fromkeys(spans))
    if len(spans) > 1:
        raise ValueError("여러 조회 기간이 있습니다. 이번 조회에 적용할 시작일과 종료일을 알려 주세요.")
    return {"date_from": spans[0][0].isoformat(), "date_to": spans[0][1].isoformat()} if spans else {}


def _status(text: str, target: str) -> str:
    raw = _compact(text)
    negative = r"미완료|미처리|처리대기|아직처리|미해결|(?:완료|처리|해결)(?:되지|하지)?(?:않|안)(?:은|된|한)?"
    unfinished = bool(re.search(negative, raw))
    positive_text = re.sub(negative, "", raw)
    finished = "완료" in positive_text or "해결된" in positive_text
    if unfinished and finished:
        raise ValueError("서로 다른 상태 조건이 있습니다. 조회할 업무별로 미완료 또는 완료 상태를 알려 주세요.")
    if "미해결" in raw or "해결되지않" in raw:
        return "open" if target in ("cases", "errors") else "err"
    if unfinished:
        return "open" if target in ("cases", "errors") else "todo"
    if finished:
        return "resolved" if target == "errors" else "done"
    if target not in ("errors", "case", "mail") and ("오류" in raw or "실패" in raw):
        # "견적과 오류" is two lookups, not only quotes that failed.
        if not re.search(r"(?:와|과|및|하고|이랑|,).*?(?:오류|실패)", raw):
            return "err"
    if target == "cases" and "진행중" in raw:
        return "open"
    if "보류" in raw or "진행중" in raw:
        raise ValueError("현재 조회 상태는 전체·미완료·완료·오류를 지원합니다. 어떤 상태로 조회할까요?")
    if any(word in raw for word in ("전체", "모든", "전부")):
        return "all"
    return ""


def _model_rows(plan: dict) -> list[dict]:
    if not isinstance(plan, dict):
        raise ValueError("조회 계획을 읽지 못했습니다. 조회할 업무를 다시 알려 주세요.")
    clarification = plan.get("clarification")
    if clarification:
        raise ValueError(clarification[:1000] if isinstance(clarification, str) else "조회 대상과 조건을 다시 알려 주세요.")
    if plan.get("queries") is not None:
        rows = plan["queries"]
        if not isinstance(rows, list) or not rows or any(not isinstance(x, dict) for x in rows):
            raise ValueError("조회 대상과 조건은 queries 배열로 지정해 주세요.")
    else:
        targets = plan.get("targets", plan.get("target", []))
        targets = [targets] if isinstance(targets, str) else targets
        if not isinstance(targets, list):
            raise ValueError("조회할 업무 종류를 알려 주세요.")
        rows = [{"target": target, **{key: plan[key] for key in ("filters", "customer", "case_id", "email_id") if plan.get(key)}}
                for target in targets if isinstance(target, str) and target in TARGETS]
    if len(rows) > MAX_QUERIES:
        raise ValueError("한 번에 최대 8개 조건 조합을 조회할 수 있습니다. 조회 범위를 나누어 알려 주세요.")
    for row in rows:
        if not isinstance(row.get("target"), str) or row["target"] not in TARGETS:
            raise ValueError("지원하지 않는 조회 대상입니다. 메일·견적·주문·Case 중 조회할 업무를 알려 주세요.")
        if set(row) - {"target", "filters", "customer", "case_id", "email_id", "request"}:
            raise ValueError("지원하지 않는 조회 인자가 있습니다. 고객사·기간·상태·검색어로 조건을 알려 주세요.")
        if plan.get("queries") is not None:
            if row["target"] == "mail" and row.get("filters"):
                raise ValueError("메일 상세 조회는 email_id로 지정합니다. 조건 조회는 업무 목록에서 사용해 주세요.")
            mcmail_query_filters.normalize(row["target"], row.get("filters"))
    return rows


def queries_from_plan(query: str, plan: dict) -> list[dict]:
    text = request_text(query)
    if re.search(r"(?:수량|단가|금액|가격|합계|매출)[^.!?\n]{0,20}(?:이상|이하|초과|미만|[<>]=?)|"
                 r"\d[\d,.]*\s*(?:개|건|EA|원|달러|만원|억원|%)\s*(?:이상|이하|초과|미만)", text, re.I):
        raise ValueError("수량·단가·금액 비교 조건은 현재 조회 필터에서 지원하지 않습니다. 고객사·기간·상태로 조회 범위를 알려 주세요.")
    rows = _model_rows(plan)
    for row in rows:
        if "request" in row and (not isinstance(row["request"], str) or not row["request"].strip()
                                 or row["request"].strip().casefold() not in text.casefold()):
            raise ValueError("조회 조건의 근거 구절이 원문과 다릅니다. 고객사별 기간·상태를 다시 알려 주세요.")
    # A question-card correction replaces an invalid old identifier. Without a
    # correction, preserve every explicitly requested ID.
    added = _latest_reply(query)
    id_source = added if _CASE.search(added) or _MAIL.search(added) else text
    exact = [{"target": "case", "case_id": x.upper()} for x in dict.fromkeys(_CASE.findall(id_source))]
    exact += [{"target": "mail", "email_id": x.upper()} for x in dict.fromkeys(_MAIL.findall(id_source))]
    if exact:
        if len(exact) > MAX_QUERIES:
            raise ValueError("한 번에 최대 8개 ID를 조회할 수 있습니다. 조회 범위를 나누어 주세요.")
        # A compound new plan can also contain independent list lookups. Legacy
        # targets are not evidence of an extra lookup beside an explicit ID.
        rows = [row for row in rows if row["target"] not in ("case", "mail")] if plan.get("queries") else []
        if not rows:
            return exact
        text = _CASE.sub("", _MAIL.sub("", text))
    added_customers = _named_customers(added)
    named = added_customers or _named_customers(text)
    referenced = _referenced_customers(query, text) if not named else []
    named = named or referenced
    rule_targets = _rule_targets(text)
    if not rows:
        rows = [{"target": t} for t in (rule_targets or (["customer"] if named else ["today"]))]
    elif plan.get("queries") is None and rule_targets and all(row["target"] in ("customer", "today") for row in rows):
        # Fix the old customer-wins routing without dropping the requested work type.
        rows = [{**row, "target": t} for t in rule_targets for row in rows]
    elif plan.get("queries") is None and named and not rule_targets:
        rows = [{**row, "target": "customer"} if row["target"] == "today" else row for row in rows]
    out = list(exact)
    for row in rows:
        target = row["target"]
        if target in ("case", "mail"):
            raise ValueError("조회할 Case 번호 또는 메일 ID를 요청에 직접 알려 주세요.")
        filters = mcmail_query_filters.normalize(target, row.get("filters"))
        basis = row.get("request") or text
        row_named = added_customers or ((_named_customers(basis) or referenced) if row.get("request") else named)
        period = _period(added) if added else {}
        if not period:
            period = _period(basis)
        if not period and row.get("request"):
            period = _period(text)  # A single shared period may precede the quoted clause.
        model_dates = {key: filters[key] for key in ("date_from", "date_to") if key in filters}
        if model_dates and not period:
            raise ValueError("요청에서 조회 기간을 확인하지 못했습니다. 시작일과 종료일을 알려 주세요.")
        # User date expressions are authoritative even if the model calculated them incorrectly.
        filters = {key: value for key, value in filters.items() if key not in ("date_from", "date_to")}
        filters.update(period)
        status = _status(added, target) if added else ""
        if not status:
            status = _status(basis, target)
        if not status and row.get("request"):
            status = _status(text, target)
        if filters.get("status") not in (None, "all") and not status:
            raise ValueError("요청에서 처리 상태 조건을 확인하지 못했습니다. 전체·미완료·완료 중 알려 주세요.")
        if status:
            filters["status"] = status
        # A labelled correction is unambiguous; arbitrary free text is not a
        # search term by itself. Keep the old source for validation, never as an
        # override of the user's newly supplied value.
        search_reply = re.search(r"(?:검색어|제품명|품목명|키워드)\s*[:=]\s*([^\n,;]+)", added)
        if search_reply:
            filters["q"] = search_reply[1].strip().strip("\"'“”‘’")
        if filters.get("q") and not any(_compact(filters["q"]) in _compact(source) for source in (basis, added)):
            raise ValueError("검색어가 요청 내용과 다릅니다. 찾을 제품명 또는 검색어를 알려 주세요.")
        who = row.get("customer") or filters.get("customer")
        if re.search(r"말고|제외|빼고|아닌", basis) and who:
            _canonical_customer(who, basis, row_named)
        if len(row_named) == 1:
            customers = row_named  # Correct an incorrect model customer using the explicit customer.
        elif len(row_named) > 1 and len({x["target"] for x in rows}) == 1 and len(rule_targets) <= 1:
            customers = row_named  # A shared work type applies to every named customer, not the model's first pick.
        elif who:
            customers = [_canonical_customer(who, basis, row_named)]
        else:
            if len(row_named) > 1 and len(rule_targets) > 1:
                raise ValueError("여러 고객사와 업무가 있습니다. 고객사별로 조회할 업무 종류를 알려 주세요.")
            customers = row_named or [None]
        for customer in customers:
            f = dict(filters)
            result = {"target": target}
            if target == "customer":
                if not customer:
                    raise ValueError("어느 고객사의 거래 현황을 조회할까요?")
                result["customer"] = customer
                f.pop("customer", None)
            elif customer:
                f["customer"] = customer
            f = mcmail_query_filters.normalize(target, f)
            if f:
                result["filters"] = f
            if result not in out:
                out.append(result)
    if len(out) > MAX_QUERIES:
        raise ValueError("한 번에 최대 8개 조건 조합을 조회할 수 있습니다. 조회 범위를 나누어 알려 주세요.")
    return out
