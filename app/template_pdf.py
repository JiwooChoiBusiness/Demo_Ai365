"""PDF 양식 → 같은 구조의 Word 양식(근사) — 양식 자동 추출 3단계(2026-09-21).

PDF 는 고쳐 쓰는 형식이 아니라 원본 그대로 채울 수 없다. 사용자 원칙("올린 원본을 최대한 참조")에 따라, PDF 의 글·표·글자 크기·굵기·색·
칸 음영·정렬·용지 크기를 읽어 **같은 구조의 Word 문서**로 옮기고, 그 뒤는 Word 흐름(표시 읽기 또는 AI 자동 인식 → 원본 채우기)을 그대로 탄다.
결과 파일은 Word 다. 옮기지 않는 것: 그림·로고, 선·도형 장식, 다단 배치, 머리글·바닥글 구분. 글자 층이 없는 스캔본은 거절한다.
읽는 순서: 쪽마다 표(page.find_tables)와 표 밖의 글 줄을 위에서 아래로. 글 줄은 같은 블록 안에서 크기·왼쪽 위치가 같고 줄 간격이 좁으면 한 문단으로
잇고, 글머리 기호로 시작하면 글머리표 문단(List Bullet)으로, 본문보다 크거나 굵은 짧은 줄은 제목(Heading)으로 옮긴다(서식은 글자에 직접 준다).

PDF form → a Word form with the same structure (an approximation) — stage 3 of automatic form extraction. A PDF cannot be filled in
place, so following the user's principle its text, tables, font sizes, weight, colours, cell shading, alignment and page size are rebuilt
as a Word document and the Word flow takes over; the result file is Word. Not carried over: pictures and logos, decorative lines and
shapes, multi-column layout, header/footer separation. Scanned PDFs without a text layer are rejected."""
from __future__ import annotations

import io
import re
from collections import Counter

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10
FONT = "맑은 고딕"
_BULLET = re.compile(r"^\s*([•·‣▪■□○●◦※\-–—*])(\s+(?=\S)|\s*$)")   # 기호만 있는 줄 = 빈 글머리표 / a lone glyph is an empty bullet


def _rgb(color: int) -> str:
    return f"{int(color) & 0xFFFFFF:06X}"


def _lines_outside(page, boxes):
    """표 밖의 글 줄 [{text,size,bold,color,x0,y0,x1,y1,block}] / text lines outside the tables"""
    import fitz
    out = []
    for bi, block in enumerate(page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            x0, y0 = min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans)
            x1, y1 = max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(b[0] - 1 <= cx <= b[2] + 1 and b[1] - 1 <= cy <= b[3] + 1 for b in boxes):
                continue
            big = max(spans, key=lambda s: len(s["text"]))
            out.append({"text": "".join(s["text"] for s in line["spans"]).strip(), "size": round(big["size"], 1),
                        "bold": bool(big["flags"] & 16) or "bold" in big["font"].lower(), "color": _rgb(big["color"]),
                        "x0": x0, "y0": y0, "x1": x1, "y1": y1, "block": bi})
    return out


def _paragraphs(lines):
    """줄 → 문단: 같은 블록·같은 크기·같은 왼쪽 위치·좁은 줄 간격이면 잇는다(글머리 기호로 시작하는 줄은 새 문단).
    Lines → paragraphs: joined when they share block, size and left edge with a small gap (a bullet always starts a new paragraph)."""
    out = []
    for ln in sorted(lines, key=lambda x: (round(x["y0"]), x["x0"])):
        prev = out[-1] if out else None
        if prev and prev["block"] == ln["block"] and prev["size"] == ln["size"] and prev["bold"] == ln["bold"] \
                and abs(prev["x0"] - ln["x0"]) < 3 and 0 <= ln["y0"] - prev["y1"] < ln["size"] * 0.9 and not _BULLET.match(ln["text"]):
            prev["text"] += " " + ln["text"]
            prev["y1"], prev["x1"] = ln["y1"], max(prev["x1"], ln["x1"])
        else:
            out.append(dict(ln))
    return out


def _cell_fill(drawings, bbox):
    """칸을 덮는 채움 사각형의 색(흰색 제외) — 라벨 칸의 음영을 옮긴다 / the fill colour of a rectangle covering the cell (label shading)"""
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    area = max(1.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    for d in drawings:
        fill, r = d.get("fill"), d.get("rect")
        if not fill or r is None or not (r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 1 <= cy <= r.y1 + 1):
            continue
        if (r.x1 - r.x0) * (r.y1 - r.y0) > area * 4:
            continue   # 쪽 전체 바탕 같은 큰 사각형은 칸 음영이 아니다 / page-wide backgrounds are not cell shading
        hexa = "".join(f"{int(round(c * 255)):02X}" for c in fill[:3])
        if hexa != "FFFFFF":
            return hexa
    return None


def to_docx(content: bytes) -> bytes:
    import fitz
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    if len(content) > MAX_BYTES:
        raise ValueError("원본 양식은 10MB 이하여야 합니다")
    try:
        pdf = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — 손상된 파일 / a damaged file
        raise ValueError("정상적인 PDF 문서가 아닙니다") from exc
    try:
        if pdf.needs_pass or pdf.is_encrypted:
            raise ValueError("암호가 걸린 PDF 는 읽을 수 없습니다")
        if pdf.page_count > MAX_PAGES:
            raise ValueError(f"PDF 양식은 {MAX_PAGES}쪽 이하여야 합니다. 양식 부분만 남겨 올려 주세요")
        pages = []
        for page in pdf:
            # 칸 음영(채움 사각형)이 있는 표는 기본 전략이 음영 가장자리까지 선으로 봐 행·열을 잘게 쪼갠다 → 선만 보는 전략을 먼저 쓴다
            # Shaded cells make the default strategy treat fill edges as lines and over-split the grid, so the strict (lines only) strategy goes first
            found = list(page.find_tables(strategy="lines_strict").tables) or list(page.find_tables().tables)
            # 표의 글은 쪽이 살아 있을 때 바로 읽어 둔다(쪽이 넘어가면 extract() 가 빈 글을 준다) / read table text while the page is alive
            tables = [{"bbox": tuple(t.bbox), "cells": [list(r.cells) for r in t.rows], "text": t.extract()} for t in found]
            boxes = [t["bbox"] for t in tables]
            pages.append({"rect": page.rect, "tables": tables, "paras": _paragraphs(_lines_outside(page, boxes)),
                          "spans": [s for b in page.get_text("dict").get("blocks", []) if b.get("type") == 0
                                    for ln in b.get("lines", []) for s in ln.get("spans", []) if s.get("text", "").strip()],
                          "drawings": page.get_drawings()})
        chars = sum(len(p["text"]) for pg in pages for p in pg["paras"]) + sum(len(s["text"]) for pg in pages for s in pg["spans"])
        if chars < 20:
            raise ValueError("글자를 읽을 수 없는 PDF(스캔본)입니다. 원본 Word 파일이나 글자가 들어 있는 PDF 를 올려 주세요")

        sizes = Counter()
        for pg in pages:
            for s in pg["spans"]:
                sizes[round(s["size"], 1)] += len(s["text"])
        body = sizes.most_common(1)[0][0] if sizes else 10.5

        doc = Document()
        first = pages[0]
        xs = [p["x0"] for p in first["paras"]] + [t["bbox"][0] for t in first["tables"]]
        xe = [p["x1"] for p in first["paras"]] + [t["bbox"][2] for t in first["tables"]]
        ys = [p["y0"] for p in first["paras"]] + [t["bbox"][1] for t in first["tables"]]
        sec = doc.sections[0]
        sec.page_width, sec.page_height = Pt(first["rect"].width), Pt(first["rect"].height)
        left = max(28.0, min(xs)) if xs else 56.0
        sec.left_margin = Pt(left)
        sec.right_margin = Pt(max(28.0, first["rect"].width - max(xe))) if xe else Pt(56)
        sec.top_margin = Pt(max(28.0, min(ys) - 4)) if ys else Pt(56)
        sec.bottom_margin = Pt(42)
        normal = doc.styles["Normal"]
        normal.font.name, normal.font.size = FONT, Pt(body)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

        def write(par, text, size, bold, color, force=False):
            run = par.add_run(text)
            run.font.name, run.font.size, run.bold = FONT, Pt(size), bold
            run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
            if color and (force or color != "000000"):   # 제목 스타일의 기본색(파랑)을 덮으려면 검정도 직접 준다 / headings need black set explicitly to beat the style's blue
                run.font.color.rgb = RGBColor.from_string(color)

        def align(par, x0, x1, lo, hi):
            width = hi - lo
            if width > 0 and abs((x0 + x1) / 2 - (lo + hi) / 2) < width * 0.04 and x0 - lo > width * 0.08:
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif width > 0 and hi - x1 < width * 0.03 and x0 - lo > width * 0.3:
                par.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        for pg in pages:
            width = pg["rect"].width
            items = [("p", p["y0"], p) for p in pg["paras"]] + [("t", t["bbox"][1], t) for t in pg["tables"]]
            for kind, _, it in sorted(items, key=lambda x: x[1]):
                if kind == "p":
                    text, bullet = it["text"], _BULLET.match(it["text"])
                    heading = not bullet and len(text) <= 60 and (it["size"] >= body * 1.12 or (it["bold"] and it["size"] >= body))
                    style = "List Bullet" if bullet else ("Heading 1" if heading else None)   # Title 스타일은 밑줄이 있어 쓰지 않는다 / the Title style draws a rule, so it is not used
                    par = doc.add_paragraph(style=style) if style else doc.add_paragraph()
                    par.paragraph_format.space_after = Pt(4)
                    if heading:
                        par.paragraph_format.space_before = Pt(10)
                    write(par, text[bullet.end():] if bullet else text, it["size"], it["bold"], it["color"], force=heading)
                    if not bullet:
                        align(par, it["x0"], it["x1"], left, width - left)
                    continue
                rows, grid = it["text"], it["cells"]
                ncols = max((len(r) for r in rows), default=0)
                if not rows or not ncols:
                    continue
                table = doc.add_table(rows=len(rows), cols=ncols)
                table.style = "Table Grid"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                edges = {}
                for cells in grid:
                    for ci, bbox in enumerate(cells):
                        if bbox is not None:
                            edges.setdefault(ci, []).append(bbox[2] - bbox[0])
                for ri, cells in enumerate(grid):
                    for ci in range(ncols):
                        bbox = cells[ci] if ci < len(cells) else None
                        cell = table.cell(ri, ci)
                        if bbox is None:
                            if ci > 0:   # 병합으로 사라진 칸 → 왼쪽 칸과 합친다 / a cell swallowed by a merge joins its left neighbour
                                table.cell(ri, ci - 1).merge(cell)
                            continue
                        if ci in edges:
                            cell.width = Pt(min(edges[ci]))
                        inside = [s for s in pg["spans"] if bbox[0] - 1 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= bbox[2] + 1
                                  and bbox[1] - 1 <= (s["bbox"][1] + s["bbox"][3]) / 2 <= bbox[3] + 1]
                        text = (rows[ri][ci] or "").strip() if ci < len(rows[ri]) else ""
                        par = cell.paragraphs[0]
                        par.paragraph_format.space_before = par.paragraph_format.space_after = Pt(2)
                        if text:
                            big = max(inside, key=lambda s: len(s["text"])) if inside else None
                            write(par, text.replace("\n", " "), round(big["size"], 1) if big else body,
                                  bool(big and (big["flags"] & 16 or "bold" in big["font"].lower())), _rgb(big["color"]) if big else None)
                            if inside:
                                align(par, min(s["bbox"][0] for s in inside), max(s["bbox"][2] for s in inside), bbox[0], bbox[2])
                        fill = _cell_fill(pg["drawings"], bbox)
                        if fill:
                            shd = OxmlElement("w:shd")
                            shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
                            cell._tc.get_or_add_tcPr().append(shd)
                doc.add_paragraph().paragraph_format.space_after = Pt(2)   # 표 뒤에는 문단이 있어야 한다 / a table must be followed by a paragraph
        out = io.BytesIO()
        doc.save(out)
        return out.getvalue()
    finally:
        pdf.close()
