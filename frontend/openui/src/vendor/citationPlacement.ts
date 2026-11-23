// 인용 번호 칩의 자리(2026-10-29 조정자 지시): OpenUI 이전 채팅 각주(static/adapter.js ai365CiteMd)처럼 칩을 문장 끝 구두점 뒤에
// 바로 붙인다. OpenUI 의 remarkCitations 가 [n] 을 인용 노드로 나눈 뒤(모든 마크다운 자리의 remark 플러그인 맨 끝, hooks.tsx
// remarkPlugins) 인용 노드 앞뒤의 글 노드를 다듬는다.
// 1. 인용 바로 앞의 공백 · 탭(줄바꿈은 아님)을 지운다: "바꿉니다 [1]" → "바꿉니다¹"
// 2. 인용(붙은 묶음 포함) 바로 뒤의 문장 구두점(. , ! ? 。 이어진 것 전부)을 인용 앞으로 옮긴다:
//    "바꿉니다 [1]." → "바꿉니다.¹", "알립니다 [1][2]." → "알립니다.¹²"
// 3. 그대로 두는 곳: 숫자 바로 뒤의 인용("3.5 [1]", "v2.0[1]"), 구두점 뒤에 숫자가 오는 경우, 앞 글이 이미 구두점으로 끝나는
//    경우, 줄 첫머리(줄바꿈 뒤)의 인용, 링크 안. 코드 안의 [n] 은 원래 인용이 되지 않는다(글 노드가 아니다).
// 인용 뒤의 공백은 build/vendorPatches.ts 가 remarkCitations 에서 먹히지 않게 고쳐 두어 "[1] 그리고" 의 띄어쓰기가 남는다. 같은 패치가
// 쉼표(, ， 、)로만 이은 나열 "[1], [2], [3]" 을 인용 노드 하나로 묶어, 여기서는 붙은 묶음과 똑같이 "문서 [1], [2], [3]에" →
// "문서¹²³에" 가 된다(뒤에 [n] 이 없는 쉼표 "문서 [1], 그리고" 는 구두점이라 "문서,¹ 그리고").
// Where the citation number chips sit (2026-10-29, coordinator's request): right after the sentence punctuation, like the
// pre-OpenUI chat footnotes (ai365CiteMd in static/adapter.js). Once OpenUI's remarkCitations has split [n] into citation
// nodes (this runs last among every markdown surface's remark plugins, hooks.tsx remarkPlugins), the text nodes around each
// citation node are tidied.
// 1. Spaces and tabs (not newlines) right before a citation are removed: "바꿉니다 [1]" → "바꿉니다¹"
// 2. Sentence punctuation right after a citation (or an adjacent group; . , ! ? 。, the whole run) moves before it:
//    "바꿉니다 [1]." → "바꿉니다.¹", "알립니다 [1][2]." → "알립니다.¹²"
// 3. Left as they are: a citation right after a number ("3.5 [1]", "v2.0[1]"), punctuation followed by a digit, text that
//    already ends in punctuation, a citation at the start of a line (after a line break), and link text. [n] inside code never
//    becomes a citation in the first place (code is not a text node).
// build/vendorPatches.ts stops remarkCitations from swallowing the whitespace after a citation, so the space in "[1] next"
// survives. The same patch makes a list joined only by commas (, ， 、) such as "[1], [2], [3]" one citation node, so here it
// behaves like an adjacent group: "문서 [1], [2], [3]에" → "문서¹²³에" (a comma with no [n] after it, "문서 [1], 그리고", is
// punctuation and becomes "문서,¹ 그리고").

/** mdast 노드(여기서 쓰는 만큼만) / An mdast node (only what is used here). */
type MdNode = {
  type: string;
  value?: unknown;
  children?: MdNode[];
  data?: { hProperties?: Record<string, unknown> };
};

// 옮기는 문장 구두점(이어진 것 전부) / the sentence punctuation that moves (the whole run)
const PUNCTUATION = /^[.,!?。]+/;
// 지우는 앞 공백: 스페이스 · 탭만 / the spaces removed before a citation: spaces and tabs only
const TRAILING_SPACES = /[ \t]+$/;

function isCitation(node: MdNode | undefined): boolean {
  return (
    !!node && node.type === "customComponent" && node.data?.hProperties?.["data-component-type"] === "citation"
  );
}

function textOf(node: MdNode): string {
  if (typeof node.value === "string") return node.value;

  return (node.children ?? []).map(textOf).join("");
}

/**
 * 인용 앞 같은 줄의 마지막 글자(공백 · 탭은 건너뛴다). 줄 첫머리이거나 줄바꿈 바로 뒤면 빈 글자.
 * The last character before a citation on the same line (spaces and tabs skipped). Empty at the start of a line or right
 * after a line break.
 */
function charBefore(children: MdNode[], index: number): string {
  for (let k = index - 1; k >= 0; k -= 1) {
    const node = children[k];

    if (node.type === "break") return "";

    const text = textOf(node).replace(TRAILING_SPACES, "");

    if (!text) continue;

    const last = text.slice(-1);

    return last === "\n" || last === "\r" ? "" : last;
  }

  return "";
}

function isText(node: MdNode | undefined): node is MdNode & { value: string } {
  return !!node && node.type === "text" && typeof node.value === "string";
}

/** 한 부모 안의 인용 노드마다 앞뒤 글을 다듬는다 / Tidies the text around every citation node of one parent. */
function placeCitations(parent: MdNode): void {
  const children = parent.children ?? [];

  for (let i = 0; i < children.length; i += 1) {
    if (!isCitation(children[i])) continue;

    const before = charBefore(children, i);

    // 줄 첫머리 · 숫자 바로 뒤는 그대로 / the start of a line and right after a number stay as they are
    if (!before || /\d/.test(before)) continue;

    const prev = children[i - 1];

    if (isText(prev)) prev.value = prev.value.replace(TRAILING_SPACES, "");

    const next = children[i + 1];

    if (!isText(next)) continue;

    const punctuation = PUNCTUATION.exec(next.value)?.[0] ?? "";

    // 구두점 뒤에 숫자(소수 등) · 앞 글이 이미 구두점이면 옮기지 않는다 / no move when a digit follows (a decimal) or the text
    // before already ends in punctuation
    if (!punctuation || /^\d/.test(next.value.slice(punctuation.length)) || PUNCTUATION.test(before)) continue;

    next.value = next.value.slice(punctuation.length);

    if (isText(prev)) {
      prev.value += punctuation;
    } else {
      // 앞이 굵게 · 링크 같은 노드면 그 뒤에 구두점 글을 끼운다 / after a bold or link node, a punctuation text goes in between
      children.splice(i, 0, { type: "text", value: punctuation });
      i += 1;
    }
  }
}

function walk(node: MdNode): void {
  // 링크 안의 글은 건드리지 않는다 / text inside links is left alone
  if (!Array.isArray(node.children) || node.type === "link" || node.type === "linkReference") return;

  placeCitations(node);

  for (const child of node.children) walk(child);
}

/** remark 플러그인(인용 노드가 만들어진 뒤에 둔다) / The remark plugin (placed after the citation nodes exist). */
export function remarkCitationPlacement() {
  return (tree: MdNode) => {
    walk(tree);
  };
}
