"""Immutable uploaded Office templates. Fill explicit slots without regenerating layout.

표시 문법(2026-09-21 확장 — 올린 원본을 최대한 그대로 따르기 위한 반복 구조 지원, Word 본문 한정):
- `{{항목}}` 단일 값. 항목 형식이 목록(info["types"][항목] == "list")이면 그 문단을 줄 수만큼 복제한다(글머리표·번호 서식은 문단 속성이라 따라온다).
- `{{묶음.항목}}` 반복 묶음 — 표의 한 행(종전) 또는 **연속된 본문 문단 묶음**(신규: 절 제목 + 글머리표들)이 항목 수만큼 늘어난다.
- `{{묶음.#}}` 묶음 안의 순번(1, 2, 3 …) — 값은 엔진이 넣는다(항목 목록에는 나오지 않는다).
Marker grammar (extended 2026-09-21 so the uploaded original is followed as closely as possible; Word body only): `{{slot}}` single
value (a list-typed slot clones its paragraph per line), `{{group.field}}` repeating group — a table row (as before) or a run of
consecutive body paragraphs (new), `{{group.#}}` the 1-based index inside a group (filled by the engine, never listed as a field)."""
from __future__ import annotations

import copy
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from lxml import etree
from app import db

MAX_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 100          # 반복 묶음·목록 한 개의 최대 항목 수 / max items of one repeating group or list
SLOT = re.compile(r"\{\{\s*([\w가-힣 -]{1,40}(?:\.(?:#|[\w가-힣 -]{1,40}))?)\s*\}\}")
W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
     "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
PARTS = r"(?:word/(?:document|header\d+|footer\d+)|ppt/slides/slide\d+)\.xml"
BODY_PART = "word/document.xml"   # 문단 묶음·목록 복제는 Word 본문에서만 / paragraph groups and list cloning live in the Word body only


class NoSlots(ValueError):
    """원본에 {{표시}}가 하나도 없다 — 호출부가 자동 분석(Word)으로 넘길지 정한다 / no markers at all; the caller may fall back to analysis"""


def _keys(text: str) -> list[str]:
    """슬롯 이름 — 중괄호 안 앞뒤 공백은 무시한다({{ 보고기간 }} → 보고기간; 2026-09-15 점검) / slot names, surrounding spaces ignored"""
    return [k.strip() for k in SLOT.findall(text or "")]


def _is_index(key: str) -> bool:
    return key.endswith(".#")


def init():
    with db._conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS template_files(id TEXT PRIMARY KEY, owner TEXT NOT NULL, metadata TEXT NOT NULL, content BLOB NOT NULL)")


def _archive(content: bytes, fmt: str):
    if fmt not in ("docx", "xlsx", "pptx"):
        raise ValueError("원본 양식은 Word(.docx), Excel(.xlsx), PowerPoint(.pptx)을 지원합니다")
    if len(content) > MAX_BYTES:
        raise ValueError("원본 양식은 10MB 이하여야 합니다")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        entries = archive.infolist()
        if len(entries) > 2000 or sum(i.file_size for i in entries) > 50 * 1024 * 1024:
            raise ValueError("압축 해제 크기가 너무 큰 파일입니다")
        names = archive.namelist()
        if {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}[fmt] not in names:
            raise ValueError("파일 확장자와 내용이 일치하지 않습니다")
        if any("vbaproject" in n.lower() or "/embeddings/" in n or "/externalLinks/" in n for n in names):
            raise ValueError("매크로·외부 데이터 연결·삽입 개체가 있는 양식은 지원하지 않습니다")
        return archive
    except zipfile.BadZipFile as exc:
        raise ValueError("정상적인 Office 문서가 아닙니다") from exc


def _xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("지원하지 않는 XML 선언입니다")
    return etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def _paragraphs(root):
    return root.xpath(".//w:p | .//a:p", namespaces=W)


def _text(p):
    return "".join(n.text or "" for n in p.xpath(".//w:t | .//a:t", namespaces=W))


def inspect(content: bytes, fmt: str) -> list[str]:
    fields = []
    with _archive(content, fmt) as archive:
        if fmt in ("docx", "pptx"):
            for name in archive.namelist():
                if not re.fullmatch(PARTS, name):
                    continue
                root = _xml(archive.read(name))
                for p in _paragraphs(root):
                    for key in _keys(_text(p)):
                        # 반복 묶음: 표의 행(Word 는 행이 늘어나고, 슬라이드 표는 원본 행 수 안에서 채운다) 또는 Word 본문의 문단 묶음(2026-09-21).
                        # 슬라이드·머리글의 문단 묶음은 없다. / Repeating groups: table rows (Word rows grow, slide tables fill their
                        # existing rows) or a paragraph group in the Word body — never paragraph groups on slides or in headers.
                        if "." in key and not p.xpath("ancestor::w:tr | ancestor::a:tr", namespaces=W) and name != BODY_PART:
                            raise ValueError("반복 항목은 Word 본문의 문단이나 표의 반복할 행 안에 넣어 주세요")
                        if not _is_index(key):   # 순번({{묶음.#}})은 엔진이 채운다 / the index is filled by the engine
                            fields.append(key)
        else:
            from openpyxl import load_workbook
            book = load_workbook(io.BytesIO(content))
            try:
                for sheet in book:
                    for row in sheet:
                        for cell in row:
                            if isinstance(cell.value, str):
                                # Excel 의 반복 묶음({{지출.금액}})은 행을 늘리지 않고 같은 표시가 든 행들을 위에서부터 채운다(2026-09-21 — 수식·인쇄 영역 보존)
                                # An Excel group never inserts rows: rows carrying the same markers are filled top-down (keeps formulas and print areas)
                                fields.extend(k for k in _keys(cell.value) if not _is_index(k))
            finally:
                book.close()
    fields = list(dict.fromkeys(fields))
    if not fields:
        raise NoSlots("채울 위치가 없습니다. 원본에 {{보고기간}}, {{분석}}처럼 항목을 표시해 주세요")
    if len(fields) > 80:
        raise ValueError("채울 항목은 80개 이하여야 합니다")
    return fields


def save(content: bytes, filename: str, owner: str, groups: list[str], extra: dict | None = None) -> dict:
    """원본 양식을 불변 id 로 보관한다. extra = 자동 분석이 붙이는 메타(types·analysis·source_id 등, 2026-09-21).
    Stores the form under an immutable id. extra = metadata added by the automatic analysis (types, analysis, source_id …)."""
    fmt = Path(filename).suffix.lower().lstrip(".")
    fields = inspect(content, fmt)
    init()
    info = {**(extra or {}), "id": "tf_" + uuid.uuid4().hex, "filename": Path(filename).name,
            "format": fmt, "fields": fields, "groups": list(groups)}
    with db._conn() as conn:
        conn.execute("INSERT INTO template_files VALUES(?,?,?,?)",
                     (info["id"], owner, json.dumps(info, ensure_ascii=False), content))
    return info


def save_source(content: bytes, filename: str, owner: str, groups: list[str], plan: dict) -> str:
    """표시가 없던 **원본 그대로**와 AI 표시 계획을 보관한다(항목을 끄거나 이름을 바꾸면 여기서 다시 표시본을 만든다).
    Keeps the untouched upload plus the AI marking plan; turning a slot off or renaming it re-derives the marked copy from here."""
    init()
    sid = "ts_" + uuid.uuid4().hex
    meta = {"id": sid, "kind": "source", "filename": Path(filename).name,
            "format": Path(filename).suffix.lower().lstrip("."), "groups": list(groups), "plan": plan}
    with db._conn() as conn:
        conn.execute("INSERT INTO template_files VALUES(?,?,?,?)", (sid, owner, json.dumps(meta, ensure_ascii=False), content))
    return sid


def get(file_id: str):
    init()
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM template_files WHERE id=?", (file_id,)).fetchone()
    if row is None:
        raise ValueError("원본 양식 파일을 찾을 수 없습니다")
    return json.loads(row["metadata"]), row["owner"], bytes(row["content"])


def _plain(value) -> str:
    """값 하나를 글로 — 목록이 글 자리에 오면 쉼표로 잇는다 / one value as text; a list landing in a text slot is comma-joined"""
    if isinstance(value, (list, tuple)):
        return ", ".join(_plain(v) for v in value if _plain(v).strip())
    return "" if value is None else str(value)


def _replace_paragraph(p, values):
    nodes = p.xpath(".//w:t | .//a:t", namespaces=W)
    text = "".join(n.text or "" for n in nodes)
    for match in reversed(list(SLOT.finditer(text))):
        key = match.group(1).strip()
        if key not in values:
            raise ValueError(f"채우지 않은 항목: {key}")
        value = _plain(values[key])
        offset = 0
        for node in nodes:
            original = node.text or ""
            end = offset + len(original)
            if offset < match.end() and end > match.start():
                left, right = max(0, match.start() - offset), min(len(original), match.end() - offset)
                node.text = original[:left] + (value if offset <= match.start() else "") + original[right:]
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            offset = end


_SKIP_BETWEEN = {f"{{{W['w']}}}{n}" for n in ("bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd")}
_W_P = f"{{{W['w']}}}p"


def _records(values: dict, group: str) -> list[dict]:
    """반복 묶음의 값 — 항목이 없으면 빈 묶음 하나를 남긴다(원본 양식 모양을 지우지 않는다, 사용자 원칙 2026-09-21).
    A group's records; with none, one blank instance stays so the form keeps its shape (user principle 2026-09-21)."""
    records = values.get(group)
    if records is None:
        records = []
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError(f"반복 목록 {group}은 100행 이하의 목록이어야 합니다")
    if any(not isinstance(r, dict) for r in records):
        raise ValueError("반복 행은 항목별 값이 있는 객체여야 합니다")
    return records or [{}]


def _record_values(values: dict, group: str, fields: set, record: dict, n: int, types: dict) -> dict:
    out = {**values, **{f: "" for f in fields}, f"{group}.#": n}
    for k, v in record.items():
        key = f"{group}.{k}"
        out[key] = v if types.get(key) == "list" and isinstance(v, list) else _plain(v)
    return out


def _expand_lists(paragraphs, values: dict):
    """목록 값을 가진 문단은 줄 수만큼 복제한다(글머리표·번호 서식은 문단 속성이라 따라온다). 빈 목록이면 문단 하나를 빈칸으로 남긴다.
    Clones a paragraph per line of a list value (bullets and numbering are paragraph properties); an empty list keeps one blank line."""
    out = []
    for p in paragraphs:
        key = next((k for k in _keys(_text(p)) if isinstance(values.get(k), list)), None)
        if key is None:
            out.append((p, values))
            continue
        items = [x for x in values[key] if _plain(x).strip()][:MAX_RECORDS] or [""]
        for item in items:
            clone = copy.deepcopy(p)
            p.addprevious(clone)
            out.append((clone, {**values, key: _plain(item)}))
        p.getparent().remove(p)
    return out


def _fill_rows(root, values: dict, types: dict):
    """표의 반복 행 — 같은 묶음을 가리키는 **연속된 행들**은 한 단위로 복제한다(한 건이 두 줄을 차지하는 양식, 2026-09-21).
    Repeating table rows; consecutive rows pointing at one group repeat as a unit (forms where one record spans two rows)."""
    def group_of(row):
        keys = {k for p in _paragraphs(row) for k in _keys(_text(p)) if "." in k}
        groups = {k.split(".")[0] for k in keys}
        if len(groups) > 1:
            raise ValueError("한 표 행에는 하나의 반복 목록만 지정할 수 있습니다")
        return (next(iter(groups)) if groups else None), keys
    seen = set()
    for row in list(root.xpath(".//w:tr", namespaces=W)):
        if id(row) in seen:
            continue
        group, keys = group_of(row)
        if not group:
            continue
        block, nxt = [row], row.getnext()
        while nxt is not None and nxt.tag == row.tag:
            g2, k2 = group_of(nxt)
            if g2 != group:
                break
            block.append(nxt)
            keys |= k2
            nxt = nxt.getnext()
        seen.update(id(x) for x in block)
        for n, record in enumerate(_records(values, group), 1):
            clones = [copy.deepcopy(x) for x in block]
            for c in clones:
                block[0].addprevious(c)
            row_values = _record_values(values, group, keys, record, n, types)
            for c in clones:
                for p, v in _expand_lists(_paragraphs(c), row_values):
                    _replace_paragraph(p, v)
        for x in block:
            x.getparent().remove(x)


def _fill_fixed_rows(root, values: dict, types: dict, taken: dict):
    """슬라이드 표(a:tr)의 묶음 행 — 행을 늘리면 표가 슬라이드를 넘치므로 **원본에 있는 행 수 안에서** 위에서부터 채운다(2026-09-21).
    n번째 행 = n번째 값, 값이 모자란 행은 빈칸. / Slide table rows: adding rows would overflow the slide, so records fill the
    existing rows top-down; the n-th row takes the n-th record and spare rows stay blank."""
    for row in root.xpath(".//a:tr", namespaces=W):
        keys = {k for p in _paragraphs(row) for k in _keys(_text(p)) if "." in k}
        if not keys:
            continue
        groups = {k.split(".")[0] for k in keys}
        if len(groups) > 1:
            raise ValueError("한 표 행에는 하나의 반복 목록만 지정할 수 있습니다")
        group = next(iter(groups))
        records = values.get(group) or []
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise ValueError("반복 행은 항목별 값이 있는 객체여야 합니다")
        n = taken.get(group, 0)
        taken[group] = n + 1
        record = records[n] if n < len(records) else None
        row_values = _record_values(values, group, keys, record or {}, (n + 1) if record is not None else "", types)
        for p, v in _expand_lists(_paragraphs(row), row_values):
            _replace_paragraph(p, v)


def _fill_paragraph_groups(root, values: dict, types: dict):
    """연속된 본문 문단이 같은 묶음을 가리키면 한 단위로 항목 수만큼 복제한다(절 제목 + 글머리표들). 표의 행은 _fill_rows 가 먼저 처리한다.
    Consecutive body paragraphs pointing at one group repeat as a unit (a heading plus its bullets); table rows are handled first."""
    def group_of(p):
        return next((k.split(".")[0] for k in _keys(_text(p)) if "." in k), None)
    seen = set()
    for p in [x for x in root.iter(_W_P) if group_of(x) and not x.xpath("ancestor::w:tr", namespaces=W)]:
        if id(p) in seen:
            continue
        group, block, nxt = group_of(p), [p], p.getnext()
        while nxt is not None and (nxt.tag in _SKIP_BETWEEN or (nxt.tag == _W_P and group_of(nxt) == group)):
            if nxt.tag == _W_P:
                block.append(nxt)
            nxt = nxt.getnext()
        seen.update(id(x) for x in block)
        fields = {k for x in block for k in _keys(_text(x)) if k.startswith(group + ".")}
        for n, record in enumerate(_records(values, group), 1):
            clones = [copy.deepcopy(x) for x in block]
            for c in clones:
                block[0].addprevious(c)
            for c, v in _expand_lists(clones, _record_values(values, group, fields, record, n, types)):
                _replace_paragraph(c, v)
        for x in block:
            x.getparent().remove(x)


def fill(file_id: str, values: dict, output: Path):
    info, _, content = get(file_id)
    if info.get("kind") == "source":   # 자동 분석의 원본 보관 행은 채울 수 없다 / the kept original of an analysis cannot be filled
        raise ValueError("원본 양식 파일을 찾을 수 없습니다")
    types = info.get("types") or {}
    values = dict(values)
    for key in info["fields"]:
        if "." in key:
            continue
        v = values.get(key)
        if types.get(key) == "list":   # 목록 항목: 문자열 배열(한 줄이면 글 하나도 허용) / list slot: an array of lines (a single text is fine)
            v = [v] if isinstance(v, (str, int, float, bool)) else v
            if not isinstance(v, list) or any(not isinstance(x, (str, int, float, bool)) for x in v):
                raise ValueError(f"항목 {key}에는 글 목록이 필요합니다")
            values[key] = v
        elif isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
            values[key] = _plain(v)    # 글 자리에 온 목록은 쉼표로 잇는다 / a list in a text slot is comma-joined
        elif key not in values or not isinstance(v, (str, int, float, bool)):
            raise ValueError(f"항목 {key}에는 텍스트나 숫자가 필요합니다")
    if info["format"] == "xlsx":
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(content))
        try:
            for sheet in book:
                slots_of: dict[str, list[int]] = {}   # 묶음 → 그 묶음의 표시가 든 행 번호(위에서부터) / group → rows carrying its markers, top-down
                for row in sheet:
                    for cell in row:
                        if not isinstance(cell.value, str) or not SLOT.search(cell.value):
                            continue
                        original = cell.value
                        keys = _keys(original)
                        local = dict(values)
                        for k in (k for k in keys if "." in k):
                            # 고정 칸 묶음(2026-09-21): 행을 늘리지 않고, 묶음의 n번째 행에 n번째 값을 넣는다. 값이 모자라면 그 행은 빈칸.
                            # Fixed-capacity group: no row insertion; the n-th row of a group takes the n-th record, spare rows stay blank.
                            group, field = k.split(".", 1)
                            rows = slots_of.setdefault(group, [])
                            if cell.row not in rows:
                                rows.append(cell.row)
                            records = values.get(group) or []
                            if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
                                raise ValueError("반복 행은 항목별 값이 있는 객체여야 합니다")
                            n = rows.index(cell.row)
                            record = records[n] if n < len(records) else None
                            local[k] = "" if record is None else (n + 1 if field == "#" else _plain(record.get(field)))
                        if any(k not in local or isinstance(local[k], (dict, list)) for k in keys):
                            raise ValueError("Excel 셀에 필요한 값이 없습니다")
                        exact = SLOT.fullmatch(original)
                        cell.value = local[exact.group(1).strip()] if exact else SLOT.sub(lambda m: str(local[m.group(1).strip()]), original)
                        if exact and isinstance(cell.value, str) and cell.number_format != '@' \
                                and re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", cell.value) \
                                and len(cell.value.replace('.', '').replace('-', '')) <= 15:
                            cell.value = float(cell.value) if '.' in cell.value else int(cell.value)
                        if isinstance(cell.value, str):
                            cell.data_type = "s"  # Model/user text must not become a spreadsheet formula.
            book.save(output)
        finally:
            book.close()
        return
    with _archive(content, info["format"]) as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dest:
        taken: dict[str, int] = {}   # 슬라이드 표의 고정 칸 묶음: 묶음 → 지금까지 채운 행 수(슬라이드를 넘어 이어진다) / slide tables: rows used so far per group
        for entry in archive.infolist():
            data = archive.read(entry.filename)
            if re.fullmatch(PARTS, entry.filename):
                root = _xml(data)
                _fill_rows(root, values, types)                      # Word 표 행 묶음(행이 늘어난다) / Word table rows (they grow)
                _fill_fixed_rows(root, values, types, taken)         # 슬라이드 표 행 묶음(원본 행 수 안에서) / slide table rows (within the original rows)
                if entry.filename == BODY_PART:
                    _fill_paragraph_groups(root, values, types)     # 문단 묶음(Word 본문) / paragraph groups (Word body)
                rest = [p for p in _paragraphs(root) if _keys(_text(p))]
                for p, v in _expand_lists(rest, values):             # 목록 문단 복제(Word·슬라이드 글머리표) + 단일 값 / list paragraphs and single values
                    _replace_paragraph(p, v)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            dest.writestr(entry, data)


def sample_values(info):
    """샘플 파일용 예시 값 — 반복 묶음은 2건, 목록은 2줄로 늘어나는 모습을 보여 준다. 자동 분석이 읽은 원본 예시가 있으면 그것을 쓴다.
    Example values for the sample file: groups get two records and lists two lines; examples read by the analysis win when present."""
    types = info.get("types") or {}
    seen = {s.get("name"): str(s.get("example") or "").strip() for s in ((info.get("analysis") or {}).get("slots") or [])}
    values = {}
    for key in info["fields"]:
        if "." in key:
            group, field = key.split(".", 1)
            for i, rec in enumerate(values.setdefault(group, [{}, {}]), 1):
                rec[field] = [f"예시 {field} {i}-1", f"예시 {field} {i}-2"] if types.get(key) == "list" else f"예시 {field} {i}"
        elif types.get(key) == "list":
            values[key] = [f"예시 {key} 1", f"예시 {key} 2"]
        else:
            values[key] = seen.get(key) or f"예시 {key}"
    return values
