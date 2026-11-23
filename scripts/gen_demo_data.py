"""데모 데이터 생성기 — 지식관리 PDF 6종(8~10p) + 데이터 CSV 6종(~100행×7열).

- CSV: data/csv/ 에 저장 → 서버 기동/데이터 에이전트 실행 시 DuckDB VIEW로 자동 등록
- PDF: data/knowledge/ 에 저장 → 서버 기동 시 kb.index_all 백그라운드 인덱싱(임베딩) 대상
- 한국어 텍스트는 Malgun Gothic을 임베드해 PyMuPDF로 추출 가능하게 렌더
재실행 시 동일 시드로 같은 데이터가 재생성된다(증분 인덱싱은 해시로 변경 감지).
"""

import csv
import datetime as dt
import os
import random
from pathlib import Path

import fitz  # PyMuPDF

random.seed(42)

BASE = Path(__file__).resolve().parent.parent
CSV_DIR = BASE / "data" / "csv"
KB_DIR = BASE / "data" / "knowledge"
CSV_DIR.mkdir(parents=True, exist_ok=True)
KB_DIR.mkdir(parents=True, exist_ok=True)

FONT_REG = r"C:\Windows\Fonts\malgun.ttf"
FONT_BD = r"C:\Windows\Fonts\malgunbd.ttf"

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류전홍고문양손배")
GIVEN = ["민준", "서연", "도윤", "지우", "하준", "서윤", "지호", "예준", "주원", "지유",
         "준우", "수아", "건우", "지민", "현우", "민서", "우진", "은우", "유준", "채원",
         "지훈", "수빈", "예린", "시우", "다은", "juno", "하린", "선우", "유나", "재윤"]


def kname():
    return random.choice(SURNAMES) + random.choice(GIVEN)


def rand_date(y0, y1):
    start = dt.date(y0, 1, 1)
    end = dt.date(y1, 12, 31)
    return (start + dt.timedelta(days=random.randint(0, (end - start).days))).isoformat()


def write_csv(name, header, rows):
    path = CSV_DIR / name
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path, len(rows), len(header)


# ---------------------------------------------------------------------------
# CSV 6종 (각 7열)
# ---------------------------------------------------------------------------

def gen_hr_employees():
    depts = ["영업", "개발", "마케팅", "인사", "재무", "생산", "품질", "연구", "고객지원"]
    titles = ["사원", "대리", "과장", "차장", "부장", "팀장", "수석"]
    rows = []
    for i in range(1, 101):
        status = random.choices(["재직", "휴직", "퇴직"], weights=[85, 8, 7])[0]
        rows.append([
            f"E{1000 + i}", kname(), random.choice(depts), random.choice(titles),
            rand_date(2015, 2025), random.randint(3500, 12000) * 10000, status,
        ])
    return write_csv("hr_employees.csv",
                     ["emp_id", "name", "dept", "title", "hire_date", "annual_salary", "status"], rows)


def gen_sales_branch_monthly():
    branches = {"서울중앙": "수도권", "수원": "수도권", "인천": "수도권", "부산": "영남",
                "대구": "영남", "울산": "영남", "대전": "충청", "광주": "호남"}
    rows = []
    for b, region in branches.items():
        for m in range(1, 13):
            target = random.randint(80, 320) * 1_000_000
            sales = int(target * random.uniform(0.7, 1.25))
            rows.append([
                f"2025-{m:02d}", b, region, sales, target,
                round(sales / target * 100, 1), random.randint(120, 1600),
            ])
    return write_csv("sales_branch_monthly.csv",
                     ["month", "branch", "region", "sales_amount", "target_amount",
                      "achievement_pct", "orders_count"], rows)


def gen_inventory_stock():
    parts = ["열교환기", "순환펌프", "가스버너", "온도센서", "압력밸브", "제어보드", "팽창탱크",
             "연소팬", "점화플러그", "배기연도", "필터모듈", "디스플레이패널", "안전밸브", "감압밸브"]
    wh = ["중앙창고", "부산창고", "대전창고"]
    rows = []
    for i in range(1, 101):
        safety = random.randint(20, 200)
        rows.append([
            f"ITM-{2000 + i}", f"{random.choice(parts)} {random.choice(['A', 'B', 'C', 'S'])}형",
            random.choice(wh), random.randint(0, 800), safety,
            random.randint(8, 450) * 1000, rand_date(2025, 2026),
        ])
    return write_csv("inventory_stock.csv",
                     ["item_code", "item_name", "warehouse", "stock_qty", "safety_stock",
                      "unit_price", "last_inbound_date"], rows)


def gen_marketing_campaigns():
    channels = ["네이버", "카카오", "구글", "인스타그램", "유튜브", "이메일"]
    rows = []
    for i in range(1, 101):
        impressions = random.randint(5000, 500000)
        clicks = int(impressions * random.uniform(0.005, 0.06))
        conversions = int(clicks * random.uniform(0.01, 0.12))
        rows.append([
            f"CMP-{i:04d}", random.choice(channels), rand_date(2025, 2025),
            impressions, clicks, conversions, random.randint(50, 5000) * 1000,
        ])
    return write_csv("marketing_campaigns.csv",
                     ["campaign_id", "channel", "start_date", "impressions", "clicks",
                      "conversions", "spend"], rows)


def gen_support_tickets():
    ch = ["전화", "이메일", "챗봇", "홈페이지"]
    cat = ["설치문의", "A/S접수", "환불요청", "제품문의", "불만접수"]
    pri = ["낮음", "보통", "높음", "긴급"]
    st = ["접수", "처리중", "완료", "보류"]
    rows = []
    for i in range(1, 101):
        rows.append([
            f"T-{20260000 + i}", rand_date(2026, 2026), random.choice(ch), random.choice(cat),
            random.choices(pri, weights=[30, 40, 20, 10])[0],
            round(random.uniform(0.5, 72.0), 1),
            random.choices(st, weights=[15, 25, 50, 10])[0],
        ])
    return write_csv("support_tickets.csv",
                     ["ticket_id", "created_date", "channel", "category", "priority",
                      "resolution_hours", "status"], rows)


def gen_finance_expenses():
    depts = ["영업", "개발", "마케팅", "인사", "재무", "생산", "품질", "연구", "고객지원"]
    accounts = ["인건비", "마케팅비", "연구개발비", "일반관리비", "복리후생비"]
    rows = []
    combos = [(m, d) for m in range(1, 13) for d in depts]
    random.shuffle(combos)
    for m, d in combos[:100]:
        budget = random.randint(20, 300) * 1_000_000
        actual = int(budget * random.uniform(0.75, 1.2))
        rows.append([
            f"2025-{m:02d}", d, random.choice(accounts), budget, actual,
            actual - budget, "초과" if actual > budget else "이내",
        ])
    return write_csv("finance_expenses.csv",
                     ["month", "dept", "account", "budget", "actual", "variance", "status"], rows)


CSV_GENS = [gen_hr_employees, gen_sales_branch_monthly, gen_inventory_stock,
            gen_marketing_campaigns, gen_support_tickets, gen_finance_expenses]


# ---------------------------------------------------------------------------
# PDF 6종 (8~10페이지)
# ---------------------------------------------------------------------------

W, H = fitz.paper_size("a4")
MX, MT, MB = 56, 72, 72
LINE = 18.0

_font_reg = fitz.Font(fontfile=FONT_REG)
_font_bd = fitz.Font(fontfile=FONT_BD)


def _wrap(text, font, size, max_w):
    out, line = [], ""
    for token in text.split(" "):
        cand = (line + " " + token).strip()
        if font.text_length(cand, fontsize=size) <= max_w:
            line = cand
            continue
        if line:
            out.append(line)
        if font.text_length(token, fontsize=size) <= max_w:
            line = token
        else:  # 한 토큰이 너무 길면 글자 단위로 분할
            cur = ""
            for ch in token:
                if font.text_length(cur + ch, fontsize=size) <= max_w:
                    cur += ch
                else:
                    out.append(cur)
                    cur = ch
            line = cur
    if line:
        out.append(line)
    return out


# 표지/조항/부칙 등 구조 라벨 — 언어별. 본문 내용은 각 DOCS에 직접 작성한다.
LABELS = {
    "ko": {
        "sub": "문서번호 {code}   ·   시행일 {date}",
        "contents": "목     차",
        "chap_toc": "제{i}장  {chap}",
        "foot": "{company}  ·  본 문서는 사내 한정 자료입니다.",
        "art": "제{n}조 ({sub})",
        "addendum": "부칙",
        "addendum_body": "이 규정은 {date}부터 시행한다. 종전의 관련 규정은 이 규정으로 갈음한다.",
    },
    "en": {
        "sub": "Doc No. {code}    ·    Effective {date}",
        "contents": "Contents",
        "chap_toc": "Chapter {i}.  {chap}",
        "foot": "{company}  ·  For internal use only.",
        "art": "Section {n}. {sub}",
        "addendum": "Addendum",
        "addendum_body": "This document takes effect on {date} and supersedes any prior related policy.",
    },
}


def build_doc(meta, blocks):
    """blocks: [(kind, text)] kind in {h1, h2, body}. 8~10페이지 자동 맞춤은 호출부에서."""
    L = LABELS[meta.get("lang", "ko")]
    doc = fitz.open()

    # --- 표지 ---
    cover = doc.new_page(width=W, height=H)
    tw = fitz.TextWriter(cover.rect)
    tsize = 26
    for ln in _wrap(meta["title"], _font_bd, tsize, W - 2 * MX):
        x = (W - _font_bd.text_length(ln, fontsize=tsize)) / 2
        tw.append((x, 300), ln, font=_font_bd, fontsize=tsize)
        tw.write_text(cover)
        tw = fitz.TextWriter(cover.rect)
    sub = L["sub"].format(code=meta["code"], date=meta["date"])
    tw.append(((W - _font_reg.text_length(sub, fontsize=12)) / 2, 348), sub, font=_font_reg, fontsize=12)
    tw.append((MX, 470), L["contents"], font=_font_bd, fontsize=13)
    ty = 496
    for i, (chap, _) in enumerate(meta["chapters"], start=1):
        tw.append((MX + 14, ty), L["chap_toc"].format(i=i, chap=chap), font=_font_reg, fontsize=11)
        ty += 22
    foot = L["foot"].format(company=meta["company"])
    tw.append((MX, H - 54), foot, font=_font_reg, fontsize=9)
    tw.write_text(cover)

    # --- 본문 ---
    page = tw = None
    y = 0

    def new_page():
        nonlocal page, tw, y
        if tw is not None:
            tw.write_text(page)
        page = doc.new_page(width=W, height=H)
        tw = fitz.TextWriter(page.rect)
        y = MT

    def emit(text, font, size, gap_before, gap_after, indent=0):
        nonlocal y
        y += gap_before
        for ln in _wrap(text, font, size, W - 2 * MX - indent):
            if y + LINE > H - MB:
                new_page()
            tw.append((MX + indent, y), ln, font=font, fontsize=size)
            y += size * 1.55
        y += gap_after

    new_page()
    for kind, text in blocks:
        if kind == "h1":
            if y > MT + 1:
                new_page()
            emit(text, _font_bd, 14, 4, 8)
        elif kind == "h2":
            emit(text, _font_bd, 11.5, 8, 3)
        else:
            for para in text.split("\n"):
                emit(para, _font_reg, 10.8, 0, 5, indent=8 if para.strip()[:1].isdigit() else 0)
    if tw is not None:
        tw.write_text(page)
    return doc


FILLER_KO = [
    ("준용", "이 규정에 정하지 아니한 사항은 관계 법령, 단체협약 및 회사의 일반 방침에 따른다. 해석상 이견이 있는 경우 소관 부서의 유권해석에 따르며, 필요한 경우 경영진의 결정을 받는다."),
    ("개정 절차", "이 문서의 개정이 필요한 경우 소관 부서가 개정안을 마련하여 관련 부서의 의견을 수렴한 뒤 경영진의 승인을 받는다. 개정된 내용은 사내 공지 및 그룹웨어를 통해 전 임직원에게 안내한다."),
    ("문서의 보존", "이 문서와 관련하여 생성된 기록은 관계 법령이 정한 기간 동안 안전하게 보존하며, 보존기간이 경과한 문서는 정해진 절차에 따라 안전하게 폐기한다."),
    ("교육 및 안내", "소관 부서는 임직원이 이 문서의 내용을 충분히 숙지할 수 있도록 정기적으로 교육을 실시하고, 신규 입사자에게는 입사 시 별도의 안내를 제공한다."),
    ("협조 의무", "전 부서와 임직원은 이 문서의 원활한 운영을 위하여 상호 협조하여야 하며, 소관 부서의 자료 요청 및 점검에 성실히 응하여야 한다."),
    ("책임과 권한", "소관 부서는 이 문서의 운영 전반을 총괄하며, 각 부서장은 소속 구성원이 관련 절차를 준수하도록 관리·감독할 책임을 진다."),
]

FILLER_EN = [
    ("Interpretation", "Matters not specified in this document follow applicable laws and the company's general policies. In case of differing interpretations, the owning department's ruling applies, and management's decision is sought where necessary."),
    ("Amendments", "When this document needs to be revised, the owning department prepares a draft, gathers input from related teams, and obtains management approval. Revisions are announced to all employees via internal notices and the groupware."),
    ("Recordkeeping", "Records created in connection with this document are retained securely for the period required by applicable law, and documents past their retention period are disposed of securely per the defined procedure."),
    ("Training and Awareness", "The owning department provides regular training so employees understand this document, and gives new hires a separate briefing at onboarding."),
    ("Cooperation", "All departments and employees cooperate to ensure the smooth operation of this document and respond in good faith to the owning department's requests and reviews."),
    ("Roles and Responsibilities", "The owning department oversees the operation of this document, and each manager is responsible for ensuring their team members follow the relevant procedures."),
]


def doc_to_blocks(meta):
    L = LABELS[meta.get("lang", "ko")]
    blocks, n = [], 0
    for chap, arts in meta["chapters"]:
        blocks.append(("h1", chap))
        for sub, body in arts:
            n += 1
            blocks.append(("h2", L["art"].format(n=n, sub=sub)))
            blocks.append(("body", body))
    meta["_artno"] = n
    return blocks


def fit_and_save(meta):
    """8~10페이지가 되도록 부칙·일반조항을 가감해 저장."""
    lang = meta.get("lang", "ko")
    L = LABELS[lang]
    filler = FILLER_EN if lang == "en" else FILLER_KO
    blocks = doc_to_blocks(meta)
    fi = 0
    for _ in range(200):
        doc = build_doc(meta, blocks)
        pc = doc.page_count
        if pc < 8:
            doc.close()
            meta["_artno"] += 1
            sub, body = filler[fi % len(filler)]
            if fi >= len(filler):
                sub = f"{sub} {fi // len(filler) + 1}"
            blocks += [("h2", L["art"].format(n=meta["_artno"], sub=sub)), ("body", body)]
            fi += 1
            continue
        if pc > 10:
            doc.close()
            blocks = blocks[:-2] if len(blocks) > 4 else blocks
            continue
        break
    # 마지막 부칙
    blocks.append(("h1", L["addendum"]))
    blocks.append(("body", L["addendum_body"].format(date=meta["date"])))
    doc = build_doc(meta, blocks)
    if doc.page_count > 10:  # 부칙으로 넘쳤으면 한 조 제거 후 재구성
        blocks = blocks[:-4] + blocks[-2:]
        doc.close()
        doc = build_doc(meta, blocks)
    path = KB_DIR / meta["filename"]
    doc.save(str(path))
    pc = doc.page_count
    doc.close()
    return path, pc


COMPANY = "주식회사 나비엔테크"
DOCS = [
    {
        "filename": "정보보안_정책_v1.pdf", "title": "정보보안 정책", "code": "SEC-2026-001",
        "date": "2026-01-01", "company": COMPANY,
        "chapters": [
            ("총칙", [
                ("목적", "이 정책은 회사의 정보자산을 기밀성·무결성·가용성 측면에서 보호하고, 정보보안 사고를 예방하기 위하여 임직원이 준수하여야 할 기본 사항을 정함을 목적으로 한다."),
                ("적용 범위", "이 정책은 회사의 모든 임직원과 협력업체 인력, 그리고 회사가 운영하는 모든 정보시스템·네트워크·문서에 적용한다."),
                ("용어의 정의", "이 정책에서 사용하는 용어의 뜻은 다음과 같다.\n1. 정보자산이란 업무상 생성·취득한 데이터와 이를 처리하는 시스템을 말한다.\n2. 기밀정보란 외부에 공개될 경우 회사에 손해를 끼칠 수 있는 정보를 말한다.\n3. 보안사고란 정보자산의 유출·훼손·변조 등 보안에 영향을 주는 사건을 말한다."),
            ]),
            ("계정 및 접근통제", [
                ("계정 관리", "모든 시스템 계정은 1인 1계정을 원칙으로 하며, 타인과 공유하지 아니한다. 퇴직·부서이동 시 계정 권한은 지체 없이 회수하거나 조정한다."),
                ("비밀번호", "비밀번호는 영문 대소문자·숫자·특수문자를 조합하여 10자리 이상으로 설정하고, 최소 분기 1회 이상 변경한다. 동일 비밀번호의 재사용을 금지한다."),
                ("접근 권한", "정보시스템 접근 권한은 업무상 필요한 최소한의 범위로 부여하는 것을 원칙으로 한다. 권한 부여·변경은 소관 부서장의 승인을 받아야 한다."),
                ("다중 인증", "외부망에서 사내 시스템에 접속하거나 중요 시스템에 접근할 때에는 다중 인증을 적용하여야 한다."),
            ]),
            ("데이터 보호", [
                ("기밀정보 취급", "기밀정보는 인가된 자만 열람할 수 있도록 관리하고, 저장·전송 시 암호화하여야 한다. 출력물은 보안 등급을 표시하고 잠금 장치가 있는 장소에 보관한다."),
                ("외부 반출", "기밀정보를 외부로 반출하거나 외부 저장매체에 복사할 때에는 소관 부서장의 승인을 받아야 하며, 반출 이력을 기록한다."),
                ("백업", "중요 데이터는 정기적으로 백업하고, 백업본은 원본과 분리된 장소에 보관한다. 복구 절차는 주기적으로 점검한다."),
            ]),
            ("시스템 및 네트워크 운영", [
                ("단말 보안", "업무용 단말에는 회사가 승인한 백신·보안 프로그램을 설치하고 항상 최신 상태로 유지한다. 화면 보호기와 자동 잠금을 설정한다."),
                ("소프트웨어 관리", "업무용 단말에는 정품·승인된 소프트웨어만 설치한다. 출처가 불분명한 프로그램의 설치 및 실행을 금지한다."),
                ("네트워크 보안", "사내 네트워크는 용도에 따라 분리 운영하며, 외부 침입을 차단하기 위한 보안 장비를 운영한다. 비인가 무선 공유기의 사용을 금지한다."),
            ]),
            ("사고 대응 및 점검", [
                ("사고 신고", "임직원은 보안사고를 인지한 즉시 정보보안 담당 부서에 신고하여야 한다. 신고를 지연하거나 은폐하여서는 아니 된다."),
                ("사고 처리", "정보보안 담당 부서는 신고된 사고에 대하여 원인 분석·피해 최소화·재발 방지 조치를 수행하고 그 결과를 기록한다."),
                ("정기 점검", "소관 부서는 연 1회 이상 정보보안 점검을 실시하고, 발견된 취약점에 대하여 개선 계획을 수립·이행한다."),
            ]),
        ],
    },
    {
        "filename": "임직원_복리후생_안내.pdf", "title": "임직원 복리후생 안내", "code": "HR-2026-WELF",
        "date": "2026-01-01", "company": COMPANY,
        "chapters": [
            ("총칙", [
                ("목적", "이 안내는 임직원의 안정적인 생활과 근무 만족도 향상을 위하여 회사가 제공하는 복리후생 제도의 종류와 이용 방법을 정함을 목적으로 한다."),
                ("적용 대상", "이 제도는 정규직 임직원에게 적용함을 원칙으로 하며, 일부 제도는 근속기간·고용형태에 따라 적용 범위가 달라질 수 있다."),
            ]),
            ("휴가 및 휴직", [
                ("연차유급휴가", "연차유급휴가는 근로기준법에 따라 부여한다. 입사 1년 미만자는 1개월 개근 시 1일의 유급휴가가 발생하며, 1년 이상 근속자는 15일의 연차가 부여되고 근속연수에 따라 가산된다."),
                ("경조사 휴가", "경조사 휴가는 다음 각 호에 따라 부여한다.\n1. 본인 결혼 5일\n2. 자녀 결혼 1일\n3. 배우자 출산 10일\n4. 부모·배우자 사망 5일\n5. 조부모·형제자매 사망 3일"),
                ("병가", "업무 외 질병·부상으로 근무가 어려운 경우 연 60일 한도로 병가를 사용할 수 있으며, 3일을 초과하는 경우 의사의 진단서를 제출한다."),
                ("육아 지원", "만 8세 이하 자녀를 둔 임직원은 육아휴직 및 육아기 근로시간 단축을 신청할 수 있으며, 회사는 관련 법령에 따라 이를 보장한다."),
            ]),
            ("경제적 지원", [
                ("경조금", "임직원의 경조사에 대하여 회사 규정이 정한 경조금을 지급한다. 지급 기준은 별도의 경조 기준표에 따른다."),
                ("학자금 및 교육비", "본인 및 자녀의 학자금에 대하여 회사가 정한 기준에 따라 지원하며, 직무 관련 자격 취득·교육비의 일부를 지원한다."),
                ("주택자금 대출", "근속 1년 이상 임직원을 대상으로 주택자금 대출을 저리로 지원할 수 있으며, 한도와 조건은 매년 별도로 공지한다."),
            ]),
            ("건강 및 생활 지원", [
                ("건강검진", "전 임직원에게 연 1회 종합건강검진을 제공하며, 만 35세 이상 임직원에게는 상위 검진 항목을 추가로 지원한다."),
                ("단체보험", "회사는 임직원을 피보험자로 하는 단체상해·실손보험에 가입하여 업무상·업무 외 재해에 대비한다."),
                ("사내 복지시설", "구내식당, 휴게실, 수유실 등 복지시설을 운영하며, 임직원은 이용 수칙을 준수하여 이용한다."),
                ("선택적 복지", "임직원에게 연간 복지포인트를 부여하여 자기계발·건강·문화 등 항목에 자율적으로 사용하도록 한다."),
            ]),
            ("신청 및 운영", [
                ("신청 방법", "각 복리후생 제도의 신청은 그룹웨어의 신청 메뉴를 통하여 접수하며, 증빙이 필요한 경우 관련 서류를 함께 제출한다."),
                ("부정 수급", "허위 또는 부정한 방법으로 복리후생을 수급한 경우 해당 금액을 환수하고 관련 규정에 따라 조치할 수 있다."),
            ]),
        ],
    },
    {
        "filename": "출장경비_처리규정.pdf", "title": "출장 및 경비 처리 규정", "code": "GA-2026-EXP",
        "date": "2026-01-01", "company": COMPANY,
        "chapters": [
            ("총칙", [
                ("목적", "이 규정은 임직원의 국내외 출장과 업무상 경비의 신청·집행·정산에 관한 기준과 절차를 정하여 경비를 합리적이고 투명하게 운영함을 목적으로 한다."),
                ("적용 범위", "이 규정은 회사의 비용으로 집행되는 모든 출장 및 업무 경비에 적용한다."),
            ]),
            ("출장 관리", [
                ("출장의 구분", "출장은 국내출장과 해외출장으로 구분하며, 당일 출장과 숙박 출장으로 나눈다."),
                ("출장 승인", "출장을 가고자 하는 임직원은 출장 목적·기간·예상 경비를 기재한 출장 신청서를 작성하여 사전에 부서장의 승인을 받아야 한다. 긴급한 경우 사후 승인을 받을 수 있다."),
                ("출장비 구성", "출장비는 다음 각 호로 구성한다.\n1. 교통비: 실비 정산을 원칙으로 한다.\n2. 숙박비: 직급별 한도 내 실비를 지원한다.\n3. 일비: 식대 및 현지 교통 등 소액 경비로 직급별 정액을 지급한다."),
                ("교통수단", "교통수단은 경제성과 효율성을 고려하여 선택한다. 항공 이용 시 일반석을 원칙으로 하되, 장거리 노선은 별도 기준에 따른다."),
            ]),
            ("경비 집행", [
                ("법인카드 사용", "업무 경비는 법인카드 사용을 원칙으로 하며, 부득이하게 개인 비용으로 지출한 경우 증빙을 갖추어 정산한다."),
                ("증빙 서류", "모든 경비는 세금계산서·신용카드 매출전표·현금영수증 등 적격 증빙을 갖추어야 한다. 증빙이 없는 경비는 원칙적으로 인정하지 아니한다."),
                ("접대비", "접대비는 업무 관련성이 있는 경우에 한하여 집행하며, 일자·장소·대상·목적을 기록하고 한도를 준수한다."),
                ("사용 금지 항목", "사적 용도의 지출, 과도한 유흥성 경비, 법령에 위반되는 지출은 회사 경비로 집행할 수 없다."),
            ]),
            ("정산 및 점검", [
                ("정산 기한", "출장 또는 경비 집행이 종료된 날부터 7근무일 이내에 정산을 완료하여야 한다. 기한을 넘긴 경우 사유를 기재한다."),
                ("정산 절차", "정산은 그룹웨어 경비 시스템에 영수증을 첨부하여 신청하며, 부서장과 재무부서의 검토·승인을 거친다."),
                ("점검 및 환수", "재무부서는 경비 집행의 적정성을 정기적으로 점검하며, 부당 집행이 확인된 경우 해당 금액을 환수한다."),
            ]),
        ],
    },
    {
        "filename": "근태_취업규칙.pdf", "title": "근태 및 취업규칙", "code": "HR-2026-WORK",
        "date": "2026-01-01", "company": COMPANY,
        "chapters": [
            ("총칙", [
                ("목적", "이 규칙은 임직원의 근로조건과 복무에 관한 기본 사항을 정하여 질서 있고 효율적인 근무 환경을 조성함을 목적으로 한다."),
                ("적용 범위", "이 규칙은 회사에 근로를 제공하는 모든 임직원에게 적용하며, 개별 근로계약에서 달리 정한 경우 그에 따른다."),
            ]),
            ("근로시간", [
                ("소정근로시간", "1일 소정근로시간은 휴게시간을 제외하고 8시간, 1주 40시간을 원칙으로 한다."),
                ("시업·종업", "표준 근무시간은 09시부터 18시까지로 하며, 점심 휴게시간은 12시부터 13시까지로 한다. 부서 특성에 따라 시차출퇴근을 운영할 수 있다."),
                ("유연근무", "회사는 업무 특성과 개인 사정을 고려하여 시차출퇴근제·선택적 근로시간제 등 유연근무제를 운영할 수 있다."),
                ("연장·야간·휴일근로", "연장·야간·휴일근로는 사전 승인을 원칙으로 하며, 근로기준법에 따라 가산수당을 지급한다."),
            ]),
            ("출근 및 휴게", [
                ("출퇴근 기록", "임직원은 정해진 방법으로 출퇴근을 기록하여야 한다. 기록을 누락하거나 허위로 기록하여서는 아니 된다."),
                ("지각·조퇴·결근", "지각·조퇴·외출은 사전에 상급자에게 보고하고 승인을 받는다. 무단결근은 징계 사유가 될 수 있다."),
                ("휴게시간", "근로시간 도중에 법정 휴게시간을 부여하며, 휴게시간은 임직원이 자유롭게 이용할 수 있다."),
            ]),
            ("휴일 및 휴가", [
                ("휴일", "주휴일은 일요일로 하며, 관공서의 공휴일과 근로자의 날을 유급휴일로 한다."),
                ("연차휴가", "연차유급휴가는 근로기준법에 따라 부여·사용하며, 회사는 연차 사용 촉진 제도를 운영할 수 있다."),
            ]),
            ("복무 및 징계", [
                ("복무 의무", "임직원은 직무를 성실히 수행하고, 회사의 명예를 훼손하거나 직장 질서를 문란하게 하는 행위를 하여서는 아니 된다."),
                ("비밀 유지", "임직원은 재직 중은 물론 퇴직 후에도 업무상 알게 된 회사의 비밀을 누설하여서는 아니 된다."),
                ("징계의 종류", "징계는 다음 각 호와 같다.\n1. 경고\n2. 견책\n3. 감급\n4. 정직\n5. 해고"),
                ("징계 절차", "징계는 사실관계 확인과 소명 기회 부여를 거쳐 공정하게 진행한다."),
            ]),
        ],
    },
    {
        "filename": "제품보증_AS정책.pdf", "title": "제품 보증 및 A/S 정책", "code": "CS-2026-WTY",
        "date": "2026-01-01", "company": COMPANY,
        "chapters": [
            ("총칙", [
                ("목적", "이 정책은 회사가 공급하는 보일러·환기 제품의 품질 보증과 사후관리(A/S) 기준을 정하여 고객 신뢰를 제고함을 목적으로 한다."),
                ("적용 대상", "이 정책은 회사가 제조·판매한 제품과 정식 유통 경로를 통하여 구매한 고객에게 적용한다."),
            ]),
            ("품질 보증", [
                ("보증 기간", "제품의 무상 보증 기간은 다음 각 호와 같다.\n1. 본체: 구입일로부터 2년\n2. 열교환기 등 핵심 부품: 구입일로부터 5년\n3. 소모성 부품: 6개월"),
                ("보증 범위", "정상적인 사용 상태에서 제조상 결함으로 고장이 발생한 경우 무상으로 수리·교체한다."),
                ("보증 제외", "다음 각 호의 경우 무상 보증에서 제외한다.\n1. 사용자의 부주의나 임의 개조로 인한 고장\n2. 천재지변에 의한 손상\n3. 비정품 부품 사용으로 인한 고장\n4. 정기 점검 미실시로 인한 성능 저하"),
            ]),
            ("설치 및 점검", [
                ("설치 기준", "제품 설치는 회사가 인증한 설치 기사가 안전 기준에 따라 수행한다. 무자격자에 의한 설치로 발생한 문제는 보증 대상에서 제외될 수 있다."),
                ("정기 점검", "안전하고 효율적인 사용을 위하여 연 1회 이상 정기 점검을 권장하며, 점검 결과는 고객에게 안내한다."),
            ]),
            ("A/S 운영", [
                ("접수 채널", "A/S 접수는 고객센터 전화, 홈페이지, 모바일 앱을 통하여 받는다. 접수 시 모델명과 증상을 함께 안내한다."),
                ("처리 기한", "A/S 접수 후 영업일 기준 2일 이내에 방문 일정을 협의하며, 부품 수급이 필요한 경우 예상 소요 기간을 사전에 안내한다."),
                ("유상 수리", "보증 기간이 경과하였거나 보증 제외 사유에 해당하는 경우 부품비와 출장·기술료를 포함한 유상 수리를 진행하며, 사전에 견적을 안내한다."),
                ("부품 보유", "제품 단종 이후에도 핵심 부품을 일정 기간 보유하여 사후관리에 차질이 없도록 한다."),
            ]),
            ("고객 보호", [
                ("환불 및 교환", "제품의 중대한 하자가 반복되는 경우 관련 법령과 소비자분쟁해결기준에 따라 교환 또는 환불을 진행한다."),
                ("불만 처리", "고객의 불만은 신속·공정하게 처리하며, 처리 결과를 고객에게 통지하고 재발 방지에 활용한다."),
            ]),
        ],
    },
    {
        "filename": "개인정보_처리방침_컴플라이언스.pdf", "title": "개인정보 처리방침 및 컴플라이언스 가이드",
        "code": "CMP-2026-PRV", "date": "2026-01-01", "company": COMPANY,
        "chapters": [
            ("총칙", [
                ("목적", "이 방침은 회사가 처리하는 개인정보를 관련 법령에 따라 안전하게 보호하고, 임직원이 준수하여야 할 컴플라이언스 기준을 정함을 목적으로 한다."),
                ("기본 원칙", "회사는 개인정보를 적법하고 정당하게 수집하며, 처리 목적에 필요한 최소한의 범위에서 처리한다."),
            ]),
            ("개인정보의 처리", [
                ("수집 항목 및 목적", "회사는 계약 이행, 고객 지원, 마케팅 등 명확한 목적을 위하여 필요한 항목만 수집하며, 수집 시 정보주체에게 그 목적을 알리고 동의를 받는다."),
                ("이용 및 제공", "개인정보는 수집 목적의 범위에서만 이용하며, 법령에 근거하거나 정보주체의 동의가 있는 경우를 제외하고 제3자에게 제공하지 아니한다."),
                ("처리 위탁", "개인정보 처리를 외부에 위탁하는 경우 수탁자와 보호 의무를 계약으로 정하고 정기적으로 점검한다."),
                ("보유 및 파기", "개인정보는 보유기간이 경과하거나 처리 목적이 달성된 경우 지체 없이 안전한 방법으로 파기한다."),
            ]),
            ("정보주체의 권리", [
                ("권리 보장", "정보주체는 자신의 개인정보에 대하여 열람·정정·삭제·처리정지를 요구할 수 있으며, 회사는 정당한 요구에 지체 없이 응한다."),
                ("아동의 보호", "만 14세 미만 아동의 개인정보를 처리하는 경우 법정대리인의 동의를 받는다."),
            ]),
            ("안전성 확보", [
                ("관리적 보호조치", "회사는 개인정보 취급자를 최소화하고 정기적인 교육을 실시하며, 내부 관리계획을 수립·시행한다."),
                ("기술적 보호조치", "개인정보는 접근 권한을 통제하고 암호화하여 보관하며, 접속 기록을 보관하고 위·변조를 방지한다."),
                ("물리적 보호조치", "개인정보가 보관된 전산실·자료실 등에 대하여 출입 통제 등 물리적 보호조치를 적용한다."),
            ]),
            ("컴플라이언스", [
                ("부패 방지", "임직원은 직무와 관련하여 부당한 금품이나 향응을 주고받아서는 아니 된다."),
                ("이해충돌 방지", "임직원은 회사의 이익과 개인의 이익이 충돌하는 상황을 회피하고, 발생 시 소속 부서에 신고한다."),
                ("위반 신고", "임직원은 법령·내부규정 위반 행위를 인지한 경우 신고 채널을 통하여 신고할 수 있으며, 회사는 신고자에게 불이익을 주지 아니한다."),
                ("사고 대응", "개인정보 유출 등 침해 사고가 발생한 경우 관련 법령에 따라 정보주체와 감독기관에 신속히 통지하고 피해를 최소화한다."),
            ]),
        ],
    },
]


COMPANY_EN = "Navientech Inc."
EN_DOCS = [
    {
        "filename": "Remote_Work_Policy_EN.pdf", "title": "Remote Work Policy", "code": "HR-EN-REMOTE",
        "date": "2026-01-01", "company": COMPANY_EN, "lang": "en",
        "chapters": [
            ("General Provisions", [
                ("Purpose", "This policy establishes the principles and procedures for remote work so that employees can work productively outside the office while protecting company information and service quality."),
                ("Scope", "This policy applies to all regular employees whose roles can be performed remotely, and to contractors where their agreement allows."),
                ("Definitions", "The terms used in this policy are defined as follows.\n1. Remote work means performing assigned duties from a location other than the company office.\n2. Hybrid work means a mix of office and remote work within a week.\n3. Core hours means the daily time window during which employees must be reachable."),
            ]),
            ("Eligibility and Approval", [
                ("Eligibility", "Eligibility for remote work depends on the nature of the role, performance, and the ability to perform duties securely off-site. Roles that require on-site presence may be excluded."),
                ("Approval Process", "An employee who wishes to work remotely submits a request stating the schedule and work location and obtains the manager's approval in advance. Approval may be reviewed periodically."),
                ("Trial Period", "New remote arrangements may begin with a trial period during which the manager and employee confirm that productivity and communication are maintained."),
            ]),
            ("Working Arrangements", [
                ("Core Hours", "Employees working remotely must be available during core hours and follow the standard working time defined in the work rules. Time worked is recorded using the designated method."),
                ("Availability", "Remote employees keep their status and calendar up to date, respond to messages within a reasonable time, and join scheduled meetings on time."),
                ("Equipment and Expenses", "The company provides or reimburses reasonable equipment required for remote work in line with the expense policy. Employees are responsible for a suitable and safe work environment."),
            ]),
            ("Security and Data Protection", [
                ("Secure Access", "Remote access to company systems must use company-approved devices and multi-factor authentication. Access over public or untrusted networks requires a secured connection such as the corporate VPN."),
                ("Confidential Information", "Confidential information must not be printed, stored, or shared on personal devices or services. Screens must be locked when unattended."),
                ("Device Management", "Devices used for remote work must run approved security software kept up to date. Lost or compromised devices must be reported to the security team immediately."),
            ]),
            ("Performance and Communication", [
                ("Performance Expectations", "Remote employees are evaluated on the same objectives and deliverables as on-site employees. Managers focus on outcomes rather than location."),
                ("Communication", "Teams agree on primary communication channels and response expectations and document key decisions so that remote and on-site members stay aligned."),
                ("Meetings", "Meetings should be accessible to remote participants, with agendas shared in advance and notes circulated afterward."),
            ]),
        ],
    },
    {
        "filename": "Business_Code_of_Conduct_EN.pdf", "title": "Business Code of Conduct", "code": "CMP-EN-CONDUCT",
        "date": "2026-01-01", "company": COMPANY_EN, "lang": "en",
        "chapters": [
            ("General Principles", [
                ("Purpose", "This Code sets out the standards of ethical and lawful behavior expected of every employee and helps protect the company's reputation and the trust of customers and partners."),
                ("Scope", "This Code applies to all directors, employees, and contractors acting on behalf of the company, regardless of location."),
                ("Our Values", "We act with integrity, treat others with respect, comply with the law, and take responsibility for our decisions."),
            ]),
            ("Integrity", [
                ("Conflicts of Interest", "Employees avoid situations where personal interests conflict with the company's interests. Any actual or potential conflict must be disclosed to the employee's manager or the compliance team."),
                ("Gifts and Entertainment", "Employees do not offer or accept gifts or entertainment that could improperly influence a business decision. Modest, customary courtesies are acceptable within the limits set by company guidelines."),
                ("Anti-Bribery and Corruption", "Bribery and corruption in any form are strictly prohibited. Employees do not pay, offer, or accept anything of value to obtain an improper advantage, including facilitation payments."),
            ]),
            ("Workplace", [
                ("Respect and Non-Discrimination", "The company is committed to a workplace free of harassment and discrimination. Employees treat colleagues fairly regardless of gender, age, disability, religion, or other protected characteristics."),
                ("Health and Safety", "Employees follow health and safety rules, report hazards promptly, and help maintain a safe working environment for everyone."),
                ("Substance-Free Workplace", "Employees do not perform duties while impaired by alcohol or illegal drugs in a way that affects safety or performance."),
            ]),
            ("Company Assets and Information", [
                ("Protection of Assets", "Employees use company assets responsibly and protect them from loss, damage, theft, and misuse. Company resources are used primarily for legitimate business purposes."),
                ("Confidentiality", "Employees protect confidential and proprietary information during and after employment and disclose it only to those authorized to receive it."),
                ("Insider Information", "Employees do not trade securities or advise others to trade based on material non-public information obtained through their work."),
            ]),
            ("Compliance and Reporting", [
                ("Compliance with Laws", "Employees comply with all applicable laws and regulations, as well as company policies, in every country where the company operates."),
                ("Reporting Concerns", "Employees promptly report suspected violations of this Code through the designated reporting channels. Reports are handled fairly and as confidentially as possible."),
                ("Non-Retaliation", "The company prohibits retaliation against anyone who reports a concern in good faith or cooperates with an investigation."),
            ]),
        ],
    },
    {
        "filename": "Cloud_Service_SLA_EN.pdf", "title": "Cloud Service Level Agreement (SLA)", "code": "CS-EN-SLA",
        "date": "2026-01-01", "company": COMPANY_EN, "lang": "en",
        "chapters": [
            ("Overview", [
                ("Purpose", "This Service Level Agreement defines the availability, support, and service commitments for the MCloudBridge cloud platform provided to the customer."),
                ("Scope", "This SLA applies to the production environment of the subscribed services and does not cover trial, beta, or free-tier features unless stated otherwise."),
                ("Definitions", "The terms used in this SLA are defined as follows.\n1. Uptime means the percentage of time the service is available in a calendar month.\n2. Downtime means a period when the production service is unavailable due to a fault attributable to the provider.\n3. Incident means an unplanned interruption or degradation of the service."),
            ]),
            ("Service Availability", [
                ("Uptime Commitment", "The provider targets a monthly uptime of 99.9% for the production service. Availability is calculated as total minutes in the month minus downtime, divided by total minutes."),
                ("Measurement", "Availability is measured by the provider's monitoring systems. Reports are made available to the customer on request and on a regular schedule."),
                ("Exclusions", "Downtime does not include the following.\n1. Scheduled maintenance announced in advance.\n2. Issues caused by the customer's systems, networks, or misuse.\n3. Force majeure events beyond the provider's reasonable control."),
            ]),
            ("Support and Response", [
                ("Support Tiers", "Support requests are classified by severity, from critical (service unavailable) to low (general questions). The customer assigns an initial severity, which the provider may adjust with justification."),
                ("Response Targets", "Target initial response times are as follows.\n1. Critical: within 1 hour.\n2. High: within 4 business hours.\n3. Normal: within 1 business day.\n4. Low: within 3 business days."),
                ("Escalation", "If a critical incident is not progressing, the customer may request escalation to senior support and engineering management through the designated contact."),
            ]),
            ("Maintenance", [
                ("Scheduled Maintenance", "Routine maintenance is performed during published maintenance windows and is announced at least 72 hours in advance whenever possible."),
                ("Emergency Maintenance", "The provider may perform emergency maintenance to address security or stability risks, with notice given as soon as practicable."),
                ("Notifications", "Maintenance and incident notifications are sent to the customer's designated contacts and posted on the service status page."),
            ]),
            ("Service Credits", [
                ("Eligibility", "If monthly uptime falls below the committed level due to provider-attributable downtime, the customer may be eligible for service credits."),
                ("Credit Schedule", "Service credits are applied as a percentage of the monthly fee based on the measured uptime shortfall, as set out in the order or pricing schedule."),
                ("Claim Process", "To receive a credit, the customer submits a claim within 30 days of the affected month, including relevant details. Credits are the customer's sole remedy for availability shortfalls."),
            ]),
        ],
    },
    {
        "filename": "API_Usage_Guide_EN.pdf", "title": "API Usage Guide", "code": "DEV-EN-API",
        "date": "2026-01-01", "company": COMPANY_EN, "lang": "en",
        "chapters": [
            ("Introduction", [
                ("Purpose", "This guide explains how to authenticate, call, and integrate with the MCloudBridge public API in a secure and reliable way."),
                ("Audience", "This guide is intended for developers integrating the API into applications and for technical staff evaluating the platform."),
                ("Base URL and Versioning", "All requests are made over HTTPS to the documented base URL. The API is versioned in the path, and breaking changes are introduced only in a new version with prior notice."),
            ]),
            ("Authentication", [
                ("API Keys", "Each request must include a valid API key in the Authorization header. Keys are issued per environment and must be kept secret; never embed a key in client-side code or a public repository."),
                ("OAuth 2.0", "For user-context access, the API supports OAuth 2.0 authorization. Applications exchange an authorization code for an access token and refresh the token before it expires."),
                ("Key Rotation", "API keys should be rotated periodically and immediately if a key is suspected to be compromised. Revoked keys stop working as soon as the change is applied."),
            ]),
            ("Requests and Responses", [
                ("Request Format", "Requests use standard HTTP methods and accept JSON bodies with the Content-Type header set to application/json. Required parameters are documented per endpoint."),
                ("Response Format", "Responses are returned as JSON with a consistent structure. Successful responses use 2xx status codes and include the requested data."),
                ("Error Codes", "Errors use standard status codes and include a machine-readable code and a human-readable message.\n1. 400 indicates an invalid request.\n2. 401 indicates missing or invalid authentication.\n3. 429 indicates the rate limit was exceeded.\n4. 5xx indicates a server-side error."),
            ]),
            ("Rate Limits and Quotas", [
                ("Limits", "Each API key is subject to per-second and per-day request limits according to the subscription plan. Current limits are returned in the response headers."),
                ("Throttling", "When a limit is exceeded the API returns a 429 status with a Retry-After header. Clients should back off and retry after the indicated interval."),
                ("Best Practices", "Clients should cache responses where appropriate, batch requests when possible, and implement exponential backoff to use quotas efficiently."),
            ]),
            ("Data and Security", [
                ("Data Handling", "Clients send only the data necessary for a request and handle returned data in accordance with their privacy obligations."),
                ("Encryption", "All traffic is encrypted in transit using TLS. Sensitive values must not be placed in URLs or logs."),
                ("Compliance", "Use of the API must comply with the platform's terms of service and applicable data-protection laws."),
            ]),
        ],
    },
]


def main():
    # GEN_ONLY 환경변수로 일부만 생성 가능: "csv" | "ko" | "en" (미설정이면 전체).
    # 기존 한국어 PDF는 재생성 시 바이트가 달라져 재인덱싱(임베딩)되므로, 영문만 추가할 땐 GEN_ONLY=en 권장.
    only = os.environ.get("GEN_ONLY", "")

    if only in ("", "csv"):
        print("=== CSV ===")
        for gen in CSV_GENS:
            path, r, c = gen()
            print(f"  {path.name}: {r}행 × {c}열")

    if only in ("", "ko"):
        print("=== PDF (KO) ===")
        for meta in DOCS:
            path, pc = fit_and_save(meta)
            with fitz.open(path) as d:
                sample = " ".join(d[1].get_text("text").split())[:80]
            print(f"  {path.name}: {pc}p | p2: {sample}")

    if only in ("", "en"):
        print("=== PDF (EN) ===")
        for meta in EN_DOCS:
            path, pc = fit_and_save(meta)
            with fitz.open(path) as d:
                sample = " ".join(d[1].get_text("text").split())[:80]
            print(f"  {path.name}: {pc}p | p2: {sample}")


if __name__ == "__main__":
    main()
