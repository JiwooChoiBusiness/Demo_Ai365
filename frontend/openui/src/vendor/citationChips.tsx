// 본문 인용 [n] = 번호 칩(2026-10-29 사용자 지시 "이전에 우리 썼던 1 2 3 이런 아이콘들"). OpenUI 이전 채팅 답의 위첨자 각주
// (static/adapter.js 의 .ai365-fn · ai365CiteMd)와 같은 모양 · 동작이다.
// - 인용 하나 = 칩 하나. 번호 = 모델이 쓴 [n] 그대로 = 루트 Card 출처 목록(src1..N)의 n 번째 = 답 아래 '출처' 띠의 n 번째 카드.
//   붙은 인용 [1][2] 는 칩 "1" "2" 를 나란히 둔다(한 묶음 안에서 같은 번호는 한 번). 목록에 없는 번호는 그리지 않는다.
// - 마우스를 올리면 브라우저 기본 title 만(출처 제목, 쪽이 있으면 " p.N", 제목이 없는 웹 출처는 도메인). 말풍선은 없다.
// - 누르면(Enter · Space 도) 그 출처를 바로 연다. 출처 띠 카드와 같은 길이다(OpenUI openSourceInNewTab → 섬의 링크 규칙
//   links.ts: ai365:// → opts.onLink, http(s) → 새 창 noopener). url 이 없는 출처(그룹웨어)처럼 열 곳이 없으면 단추가 아니다.
// 빌드 때 build/vendorPatches.ts 가 OpenUI 의 TextContentCitation(인용 말풍선 Citation 을 그리던 곳)이 이 칩을 그리게 한다.
// Inline [n] citations as number chips (the user's 2026-10-29 "the 1 2 3 icons we used before"), with the look and behaviour of
// the superscript footnotes chat answers had before OpenUI (.ai365-fn and ai365CiteMd in static/adapter.js).
// - One citation = one chip. The number is the model's [n] as written = the nth source of the root Card (src1..N) = the nth
//   card of the Sources strip under the answer. Adjacent citations [1][2] become chips "1" "2" side by side (a number repeated
//   within one group shows once). Numbers without a source draw nothing.
// - Hovering shows the browser's own title only (the source title, plus " p.N" when there is a page; a web source without a
//   title shows its domain). There is no popover.
// - A click (or Enter / Space) opens that source directly, the same way as a Sources strip card (OpenUI's openSourceInNewTab →
//   the island link rule in links.ts: ai365:// → opts.onLink, http(s) → a new tab with noopener). When there is nothing to
//   open, as with a source without a url (groupware), the chip is not a button.
// At build time build/vendorPatches.ts makes OpenUI's TextContentCitation (which drew the Citation popover) draw these chips.
import { useContext, type KeyboardEvent } from "react";

import { LangContext, label, type Lang } from "../i18n";
import { linkKind, openFromVendor } from "../links";

/** 루트 Card 의 출처 하나(OpenUI CardSourceSchema + 파비콘) / One root Card source (OpenUI's CardSourceSchema plus a favicon). */
type CardSource = { title?: unknown; sourceName?: unknown; url?: unknown };

type Open = (url: string) => unknown;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * 인용 묶음의 번호(data-citation-indices "2,1,2") → 칩 번호 [2, 1]: 양의 정수만, 쓴 순서대로, 같은 번호는 한 번.
 * A citation group's numbers (data-citation-indices "2,1,2") → the chip numbers [2, 1]: positive integers only, in the
 * order written, each once.
 */
export function citationNumbers(indices: unknown): number[] {
  const out: number[] = [];

  for (const part of String(indices ?? "").split(",")) {
    const n = Number(part.trim());

    if (Number.isInteger(n) && n > 0 && !out.includes(n)) out.push(n);
  }

  return out;
}

// 쪽 = 사내 · 로컬 지식 url 의 ?page=N(app/openui.py numbered_sources) / the page = ?page=N of a knowledge or local url
function pageOf(url: string): string {
  if (!/^ai365:\/\/(kn|local)\//i.test(url)) return "";

  const query = url.split("#")[0].split("?")[1] ?? "";

  return text(new URLSearchParams(query).get("page"));
}

// 웹 출처의 도메인(제목이 없을 때) / a web source's domain (when it has no title)
function hostOf(url: string): string {
  if (!/^https?:\/\//i.test(url)) return "";

  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

/**
 * 칩의 title: 출처 제목. 서버 제목은 이미 "문서 p.N" 이라 쪽을 두 번 붙이지 않고, 쪽이 없는 제목에만 url 의 쪽을 " p.N" 으로
 * 붙인다. 제목이 없으면 웹은 도메인, 그다음 출처명. 모두 없으면 빈 글자.
 * The chip's title: the source title. Server titles already read "doc p.N", so the page is never added twice; only a title
 * without one gets the url's page as " p.N". Without a title, the domain for the web, then the source name. Empty when all
 * are missing.
 */
export function citationTitle(source: CardSource): string {
  const url = text(source.url);
  const title = text(source.title) || hostOf(url) || text(source.sourceName);
  const page = pageOf(url);

  if (!title || !page || /(^|\s)p\.\s?\d+$/i.test(title) || title.endsWith(` p.${page}`)) return title;

  return `${title} p.${page}`;
}

function CitationChip({ n, source, lang, open }: { n: number; source: CardSource; lang: Lang; open: Open }) {
  const url = text(source.url);
  const title = citationTitle(source);
  // 화면 읽기 이름 "출처 n: 제목"(EN "Source n: title"), 제목이 없으면 "출처 n" / the accessible name; "Source n" without a title
  const name = title ? `${label(lang, "Source")} ${n}: ${title}` : `${label(lang, "Source")} ${n}`;
  const common = { className: "ai365-oui-cite", "data-citation": n, title: title || name, "aria-label": name };

  if (linkKind(url) === "ignored") {
    // 열 곳이 없다(url 없는 그룹웨어 · 규칙 밖 주소): 단추가 아니고 누르면 아무 일도 없다
    // nothing to open (url-less groupware, an address outside the rule): not a button, and a click does nothing
    return (
      <sup {...common} role="img">
        {n}
      </sup>
    );
  }

  const go = () => {
    open(url);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;

    // Space 의 화면 스크롤을 막고, 누르고 있을 때 되풀이로 여러 번 열지 않는다
    // stop Space from scrolling, and do not open again on key repeat
    event.preventDefault();

    if (!event.repeat) go();
  };

  return (
    <sup {...common} role="button" tabIndex={0} onClick={go} onKeyDown={onKeyDown}>
      {n}
    </sup>
  );
}

/**
 * TextContentCitation 자리(빌드 패치): 인용 묶음 하나(data-citation-indices)의 번호 칩. 그릴 칩이 없으면 null 이다(OpenUI 와
 * 같이 [n] 글자도 남지 않는다).
 * In TextContentCitation's place (a build patch): the number chips of one citation group (data-citation-indices). null when
 * there is no chip to draw (as in OpenUI, the [n] text is not left either).
 */
export function CitationNumbers({ indices, sources, open }: { indices: unknown; sources: unknown; open?: Open }) {
  const lang = useContext(LangContext);
  const list: unknown[] = Array.isArray(sources) ? sources : [];
  const chips = citationNumbers(indices)
    .map((n) => ({ n, source: list[n - 1] }))
    .filter((chip): chip is { n: number; source: CardSource } => typeof chip.source === "object" && chip.source !== null);

  if (chips.length === 0) return null;

  return (
    <span className="ai365-oui-cites">
      {chips.map(({ n, source }) => (
        <CitationChip key={n} n={n} source={source} lang={lang} open={open ?? openFromVendor} />
      ))}
    </span>
  );
}
