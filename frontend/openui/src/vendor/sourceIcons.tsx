// 출처 아이콘. 사내 지식(ai365://kn/…)은 데모 주색 문서, 로컬 지식(ai365://local/…)은 '로컬' 배지의 주황 문서,
// 데이터(ai365://data/… · ai365://data/bi/…)는 보라 원그래프, url 이 없는 출처(그룹웨어, 계약 9.3절)는 파랑 네 칸,
// 웹(http(s))은 지금처럼 파비콘(없으면 지구). 답 아래 출처 띠 카드의 로고 칸에 쓴다(본문 인용 [n] 은 2026-10-29 부터
// 아이콘이 아니라 번호 칩이다, citationChips.tsx).
// Source icons. Internal knowledge (ai365://kn/…) gets a document in the demo primary, local knowledge
// (ai365://local/…) the same document in the orange of the '로컬' badge, data (ai365://data/…, ai365://data/bi/…) a
// purple pie, a source without a url (groupware, contract section 9.3) a blue four-square grid, and the web (http(s))
// keeps its favicon (a globe when there is none). Used in the logo slot of the Sources strip cards under an answer
// (since 2026-10-29 inline [n] citations are number chips, not icons; see citationChips.tsx).
//
// 색 · 모양은 adapter.js 와 같다: 사내 = DS 브랜드 #4450CE(Brand 80) · 바탕 #F2F6FF(Brand 170) · 귀퉁이 #B4C6FF(Brand 140),
// 로컬 = .ai365-local-badge 의 DS 경고 틴트(2026-10-28 Figma DS: 아이콘 #BC4B09 Warning foreground 1 · 바탕 #FFF9F5 Warning background 1 ·
// 테두리 #FDCFB4 Warning border 1), 데이터 = AI365_RES_ICONS.data(#8B43E6 · 바탕 #F2E9FE), 그룹웨어 = AI365_RES_ICONS.groupware(#3B6FE0 ·
// 바탕 #E6F0FF). SVG 속성에는 CSS 변수를 쓸 수 없어 DS 값을 그대로 적는다(바탕 · 테두리는 island.css 의 --ds-* 토큰).
// Colors and shapes match adapter.js: internal = the DS brand #4450CE (Brand 80) on #F2F6FF (Brand 170) with a #B4C6FF (Brand 140)
// fold; local = .ai365-local-badge's DS warning tint (2026-10-28 Figma DS: icon #BC4B09 Warning foreground 1, ground #FFF9F5
// Warning background 1, border #FDCFB4 Warning border 1); data = AI365_RES_ICONS.data (#8B43E6 on #F2E9FE); groupware =
// AI365_RES_ICONS.groupware (#3B6FE0 on #E6F0FF). SVG attributes cannot take CSS variables, so the DS values are written as is
// (grounds and borders use the --ds-* tokens in island.css).
import { useContext } from "react";

import { LangContext, label } from "../i18n";

/** 섬이 직접 그리는 출처 종류(네트워크 요청 없음) / The source kinds the island draws itself (no network request). */
export type DocKind = "kn" | "local" | "data" | "gw";
export type SourceKind = DocKind | "web" | "other";

const DOC_KINDS: readonly DocKind[] = ["kn", "local", "data", "gw"];

/** 섬이 직접 그리는 종류인가 / Whether the island draws this kind itself. */
export function isDocKind(kind: unknown): kind is DocKind {
  return DOC_KINDS.includes(kind as DocKind);
}

/**
 * 출처 url 의 종류. url 이 없으면 그룹웨어(계약 9.3절: 그룹웨어 출처만 url 이 없다, 누를 곳이 없다).
 * The kind of a source url. No url means groupware (contract section 9.3: only groupware sources have no url, as
 * there is no page to go to).
 */
export function sourceKind(url: unknown): SourceKind {
  const value = typeof url === "string" ? url.trim() : "";

  if (!value) return "gw";
  if (/^ai365:\/\/kn\//i.test(value)) return "kn";
  if (/^ai365:\/\/local\//i.test(value)) return "local";
  if (/^ai365:\/\/data\//i.test(value)) return "data";
  if (/^https?:\/\//i.test(value)) return "web";

  return "other";
}

// 파비콘 자리에 넣는 표식(getFaviconUrl 이 돌려주고 SourceFaviconImage 가 알아본다). 네트워크로 나가지 않는다.
// The marker put in the favicon slot (returned by getFaviconUrl, recognised by SourceFaviconImage); never fetched.
const DOC_MARK = "ai365-doc:";

export function docMark(kind: DocKind): string {
  return DOC_MARK + kind;
}

/** 파비콘 값이 섬이 그리는 출처 표식이면 그 종류 / The kind when a favicon value is one of the island's markers. */
export function docKind(favicon: unknown): DocKind | null {
  if (typeof favicon !== "string" || !favicon.startsWith(DOC_MARK)) return null;

  const kind = favicon.slice(DOC_MARK.length);

  return isDocKind(kind) ? kind : null;
}

const DOC_COLORS: Record<"kn" | "local", { body: string; fold: string }> = {
  kn: { body: "#4450CE", fold: "#B4C6FF" },
  local: { body: "#BC4B09", fold: "#FDCFB4" },
};

// 그림 셋: 문서(접힌 귀퉁이, adapter 지식 카드) · 원그래프(AI365_RES_ICONS.data) · 네 칸(AI365_RES_ICONS.groupware)
// Three drawings: a document (folded corner, the adapter's knowledge card), a pie (AI365_RES_ICONS.data) and a
// four-square grid (AI365_RES_ICONS.groupware)
function GlyphPaths({ kind }: { kind: DocKind }) {
  if (kind === "data") {
    return (
      <g fill="#8B43E6">
        <path d="M11 3.05A9 9 0 1 0 20.95 13H11z" />
        <path d="M13 2.05V11h8.95A9.01 9.01 0 0 0 13 2.05z" opacity=".55" />
      </g>
    );
  }

  if (kind === "gw") {
    return (
      <g fill="none" stroke="#3B6FE0" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1.6" />
        <rect x="14" y="3" width="7" height="7" rx="1.6" />
        <rect x="3" y="14" width="7" height="7" rx="1.6" />
        <rect x="14" y="14" width="7" height="7" rx="1.6" />
      </g>
    );
  }

  const color = DOC_COLORS[kind];

  return (
    <>
      <path d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" fill={color.body} />
      <path d="M14 2v5h5z" fill={color.fold} />
    </>
  );
}

function DocGlyph({ kind, size }: { kind: DocKind; size: number }) {
  return (
    <svg
      className={`ai365-oui-doc-glyph ai365-oui-doc-glyph--${kind}`}
      data-source-kind={kind}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <GlyphPaths kind={kind} />
    </svg>
  );
}

// 타일의 이름(화면 읽기) / the tile's accessible name
const KIND_LABELS: Record<DocKind, string> = {
  kn: "Internal document",
  local: "Local document",
  data: "Data analysis",
  gw: "Groupware",
};

/**
 * 출처 로고 칸(띠 카드 20px)을 채우는 타일. 파비콘처럼 칸을 채우고 가운데에 그 종류의 그림.
 * A tile that fills a source logo slot (strip card 20px): it fills the slot the way a favicon does, with the kind's
 * drawing in the middle.
 */
export function DocIcon({ kind, size }: { kind: DocKind; size: number }) {
  const lang = useContext(LangContext);

  return (
    <span
      className={`ai365-oui-doc ai365-oui-doc--${kind}`}
      role="img"
      aria-label={label(lang, KIND_LABELS[kind])}
      data-source-kind={kind}
    >
      <DocGlyph kind={kind} size={Math.round(size * 0.68)} />
    </span>
  );
}
