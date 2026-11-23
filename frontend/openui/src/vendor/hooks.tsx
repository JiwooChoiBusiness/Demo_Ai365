// genui-lib 번들 안에서 부르는 함수 · 컴포넌트(빌드 때 build/vendorPatches.ts 가 `__ai365oui.*` 로 끼워 넣는다).
// 이 파일은 @openuidev/react-ui 를 가져오지 않는다(순환 방지).
// Functions and components called from inside the genui-lib bundle (build/vendorPatches.ts wires them in as
// `__ai365oui.*` at build time). This file never imports @openuidev/react-ui (no cycles).
import { useContext } from "react";

import { withoutCitations } from "../components/citations";
import { LangContext, currentLang, label, message } from "../i18n";
import { openFromVendor } from "../links";
import { remarkCitationPlacement } from "./citationPlacement";
import { remarkCjkFriendly } from "./cjkEmphasis";
import { docMark, isDocKind, sourceKind } from "./sourceIcons";

// 출처 아이콘(사내 · 로컬 문서 · 데이터 · 그룹웨어) / source icons (internal and local documents, data, groupware)
export { DocIcon, docKind } from "./sourceIcons";

// 본문 인용 [n] 번호 칩(TextContentCitation 자리) / the inline [n] number chips (in TextContentCitation's place)
export { CitationNumbers } from "./citationChips";

/** 포털 뿌리에 붙는 클래스(섬 CSS 와 테마 변수가 따라간다) / The class on portal roots (island CSS and theme vars follow). */
export const PORTAL_CLASS = "ai365-oui-portal";

// 차트 색: 데모 주색(#4450CE) 계열 11단. OpenUI 는 가운데부터 이웃 색을 고른다(계열이 하나면 6번째).
// Chart colors: an 11-step ramp around the demo primary (#4450CE). OpenUI picks neighbours from the middle (one
// series gets the 6th).
const CHART_PALETTE = [
  "#0B0757",
  "#1D008B",
  "#2C24A6",
  "#3940BD",
  "#4450CE",
  "#5A6BE0",
  "#7186FF",
  "#92A3FF",
  "#B3C0FF",
  "#D2DAFF",
  "#EAEEFF",
];

/** safeOpenUrl 대신 / Instead of safeOpenUrl. */
export function openUrl(url: string, _target?: string, _features?: string): Window | null {
  return openFromVendor(url);
}

/**
 * 파비콘: http(s) 출처만 구글 파비콘. 사내(ai365://kn) · 로컬(ai365://local) · 데이터(ai365://data) 출처와 url 이 없는
 * 그룹웨어 출처는 섬이 그리는 아이콘 표식(네트워크 요청 없음), 그 밖은 빈 값(지구 아이콘).
 * Favicons: Google favicons for http(s) sources only. Internal (ai365://kn), local (ai365://local) and data
 * (ai365://data) sources, and url-less groupware sources, get the island's icon marker (no network request); anything
 * else is empty (a globe).
 */
export function faviconUrl(url?: string): string {
  const kind = sourceKind(url);

  if (isDocKind(kind)) return docMark(kind);

  try {
    if (!url) return "";

    const parsed = new URL(url);

    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";

    return `https://www.google.com/s2/favicons?sz=128&domain=${parsed.hostname}`;
  } catch {
    return "";
  }
}

/**
 * 모든 마크다운 자리(MarkDownRenderer 하나를 거친다: TextContent · Callout · 단계 설명 · 인라인 글)의 remark 플러그인 끝에 한중일
 * 친화 강조(`**55%**로` 가 굵게)와 인용 칩 자리 다듬기(remarkCitations 뒤에 돌아 "바꿉니다 [1]." → "바꿉니다.¹",
 * citationPlacement.ts; 인용 노드가 없는 자리에서는 아무 일도 없다)를 더한다. 받은 목록은 그대로 둔다.
 * Every markdown surface goes through one MarkDownRenderer (TextContent, Callout, step details, inline text); CJK-friendly
 * emphasis (`**55%**로` turns bold) and the citation chip placement (it runs after remarkCitations, "바꿉니다 [1]." →
 * "바꿉니다.¹", citationPlacement.ts; nothing happens where there are no citation nodes) are added at the end of its remark
 * plugins. The given list itself is untouched.
 */
export function remarkPlugins(list: unknown): unknown[] {
  return [...(Array.isArray(list) ? list : []), remarkCjkFriendly, remarkCitationPlacement];
}

/**
 * 칩을 둘 수 없는 자리(누르면 질문을 보내는 목록 줄의 부제)에서 [n] 을 지운다(칩을 누르면 줄 동작까지 불린다).
 * Drops [n] where no chip can go (the subtitle of a list row that sends a question when clicked; a chip click would
 * fire the row's action too).
 */
export function stripCitations(text: unknown): string {
  return withoutCitations(text === null || text === undefined ? "" : String(text));
}

// react-markdown 의 defaultUrlTransform 과 같되 ai365: 를 허용 / react-markdown's defaultUrlTransform, plus ai365:
const SAFE_PROTOCOL = /^(https?|ircs?|mailto|xmpp|ai365)$/i;

export function urlTransform(value: string): string {
  const colon = value.indexOf(":");
  const questionMark = value.indexOf("?");
  const numberSign = value.indexOf("#");
  const slash = value.indexOf("/");

  if (
    colon === -1 ||
    (slash !== -1 && colon > slash) ||
    (questionMark !== -1 && colon > questionMark) ||
    (numberSign !== -1 && colon > numberSign) ||
    SAFE_PROTOCOL.test(value.slice(0, colon))
  ) {
    return value;
  }

  return "";
}

let uuidSeq = 0;

/**
 * crypto.randomUUID 대신(보안 문맥이 아니면 없다). 고유하기만 하면 된다(툴팁 묶음 이름).
 * Instead of crypto.randomUUID (missing outside secure contexts). It only has to be unique (a tooltip group name).
 */
export function uuid(): string {
  const c = globalThis.crypto as Crypto | undefined;

  if (typeof c?.randomUUID === "function") return c.randomUUID();

  uuidSeq += 1;

  return `ai365oui-${Date.now().toString(36)}-${uuidSeq.toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 기본 테마 객체 + 데모 차트 색 / The default theme object plus the demo chart colors. */
export function theme<T extends object>(base: T): T {
  return { ...base, defaultChartPalette: CHART_PALETTE };
}

// 표의 "number" 열(OpenUI 는 Col 의 type 을 받기만 하고 쓰지 않는다). 데이터 답은 Col("매출액", d1top.c2, "number") 처럼
// 서버 데이터 문장의 수를 그대로 넣으므로(계약 9.4절) 큰 수가 1250000 처럼 보인다.
// A Table's "number" columns (OpenUI accepts Col's type but never uses it). Data answers put the server's data
// statement numbers in as they are, Col("매출액", d1top.c2, "number") (contract section 9.4), so large numbers would
// show as 1250000.
const GROUP_FROM = 10000;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * "number" 열에 절댓값 1만 이상인 수가 하나라도 있으면 그 열의 모든 수를 천 단위 쉼표로(@FormatNumber 와 같은 모양,
 * 소수 둘째 자리까지). 네 자리 이하뿐인 열(연도 · 코드 · 작은 값)과 수가 아닌 칸(글 · Tag · ProgressBar · null)은 그대로.
 * When a "number" column holds any number of 10,000 or more (in absolute terms), every number in it gets thousands
 * separators (the shape of @FormatNumber, up to two decimals). Columns of four digits at most (years, codes, small
 * values) and cells that are not numbers (text, Tag, ProgressBar, null) stay as they are.
 */
export function numberColumn(data: unknown[], type: unknown): unknown[] {
  if (type !== "number" || !Array.isArray(data)) return data;
  if (!data.some((value) => isFiniteNumber(value) && Math.abs(value) >= GROUP_FROM)) return data;

  return data.map((value) => (isFiniteNumber(value) ? value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : value));
}

/** "number" 열은 머리 · 칸을 오른쪽으로 / A "number" column's header and cells align right. */
export function numberAlign(type: unknown): "right" | undefined {
  return type === "number" ? "right" : undefined;
}

/** 화면 글자(섬의 언어) / An on-screen label (in the island's language). */
export function Label({ k }: { k: string }) {
  const lang = useContext(LangContext);

  return <>{label(lang, k)}</>;
}

/** 입력 검증 문구(섬의 언어) / A validation message (in the island's language). */
export function Message({ m }: { m: unknown }) {
  const lang = useContext(LangContext);

  return <>{message(lang, m === null || m === undefined ? "" : String(m))}</>;
}

/** 문자열 속성용(마지막 render() 의 언어) / For string props (the last render()'s language). */
export function tr(key: string): string {
  return label(currentLang(), key);
}
