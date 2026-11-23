// 한중일(CJK) 친화 강조. CommonMark 은 `**55%**로` · `**"따옴표"**를` 처럼 닫는 ** 앞이 문장 부호이고 뒤가 글자(조사)이면
// 그 ** 를 닫는 구분자로 보지 않아 별표가 글자 그대로 남는다(조사가 붙는 언어의 고질 문제). 여는 쪽도 같다:
// `고객사**(주)엠클라우드**는` 의 여는 ** 는 앞이 글자이고 뒤가 문장 부호라 열지 못한다.
// CJK-friendly emphasis. CommonMark does not let the closing ** of `**55%**로` or `**"따옴표"**를` close, because it is
// preceded by punctuation and followed by a letter (a Korean particle), so the asterisks stay as text. The opening side
// has the mirror problem: in `고객사**(주)엠클라우드**는` the opening ** follows a letter and precedes punctuation.
//
// 규칙(markdown-cjk-friendly 제안과 같은 방향, * 만): 문장 부호 옆 ** 는 반대쪽이 공백 · 문장 부호일 때뿐 아니라 한중일 글자일 때도
// 열고 닫는다. 그 밖(_ 강조 · 코드 · 글자 사이의 *)은 CommonMark 그대로다.
// The rule (the direction of the markdown-cjk-friendly proposal, for * only): a ** next to punctuation opens or closes
// not only when the other side is whitespace or punctuation, but also when it is a CJK character. Everything else
// (_ emphasis, code, * between letters) stays CommonMark.
//
// 방법: micromark 의 핵심 attention 구성(micromark-core-commonmark 2.0.4, MIT, (c) Titus Wormer)을 끄고, 같은 토크나이저에
// 위 규칙만 더한 구성을 넣는다. 짝 맞추기(resolveAll)는 핵심의 것을 그대로 쓴다. 새 의존성은 없다(이미 잠긴 하위 의존성).
// How: micromark's core attention construct (micromark-core-commonmark 2.0.4, MIT, (c) Titus Wormer) is disabled and
// replaced by the same tokenizer plus the rule above; matching (resolveAll) is the core one as is. No new dependency
// (these are locked transitive dependencies already).
import { attention } from "micromark-core-commonmark";
import { classifyCharacter } from "micromark-util-classify-character";
import type { Code, Construct, Effects, Extension, State, TokenizeContext } from "micromark-util-types";

const ASTERISK = 42;
const UNDERSCORE = 95;
// classifyCharacter: 1 = 공백(줄 끝 · 문서 끝 포함), 2 = 문장 부호, undefined = 그 밖 / 1 whitespace, 2 punctuation, else other
const PUNCTUATION = 2;

// 한중일 글자 범위(BMP). 서로게이트(확장 B 이상 한자)는 넣지 않는다(그 경우 CommonMark 그대로).
// CJK ranges (BMP). Surrogates (CJK extension B and up) are left out, which keeps CommonMark for them.
const CJK_RANGES: readonly (readonly [number, number])[] = [
  [0x1100, 0x11ff], // 한글 자모 / Hangul Jamo
  [0x2e80, 0x2fff], // 부수 · 강희 부수 · 한자 구조 / CJK and Kangxi radicals, ideographic description
  [0x3000, 0x303f], // 한중일 기호 · 문장 부호 / CJK symbols and punctuation
  [0x3040, 0x30ff], // 히라가나 · 가타카나 / Hiragana, Katakana
  [0x3100, 0x31ff], // 주음 · 한글 호환 자모 · 획 / Bopomofo, Hangul compatibility jamo, strokes
  [0x3200, 0x33ff], // 둘러싼 글자 · 호환 / enclosed CJK letters, CJK compatibility
  [0x3400, 0x4dbf], // 한자 확장 A / CJK extension A
  [0x4e00, 0x9fff], // 한자 / CJK unified ideographs
  [0xa960, 0xa97f], // 한글 자모 확장 A / Hangul Jamo extended A
  [0xac00, 0xd7ff], // 한글 음절 · 자모 확장 B / Hangul syllables, Hangul Jamo extended B
  [0xf900, 0xfaff], // 호환 한자 / CJK compatibility ideographs
  [0xfe30, 0xfe4f], // 호환 꼴 / CJK compatibility forms
  [0xff00, 0xffef], // 반각 · 전각 / halfwidth and fullwidth forms
];

/** 한중일 글자인가 / Whether a character code is CJK. */
export function isCjk(code: Code): boolean {
  if (code === null || code < 0x1100) return false;

  return CJK_RANGES.some(([from, to]) => code >= from && code <= to);
}

// micromark-core-commonmark/lib/attention.js 의 tokenizeAttention 에 한중일 규칙만 더했다(그 밖은 그대로)
// micromark-core-commonmark/lib/attention.js's tokenizeAttention plus the CJK rule (nothing else changes)
function tokenizeCjkAttention(this: TokenizeContext, effects: Effects, ok: State): State {
  const attentionMarkers = this.parser.constructs.attentionMarkers.null ?? [];
  const previous = this.previous;
  const before = classifyCharacter(previous);
  let marker: Code = null;

  return start;

  function start(code: Code): State | undefined {
    marker = code;
    effects.enter("attentionSequence");

    return inside(code);
  }

  function inside(code: Code): State | undefined {
    if (code === marker) {
      effects.consume(code);

      return inside;
    }

    const token = effects.exit("attentionSequence");
    const after = classifyCharacter(code);
    const star = marker === ASTERISK;
    // 여는 쪽: 뒤가 문장 부호면 앞이 공백 · 문장 부호(CommonMark)이거나 한중일 글자(* 만) / opening: punctuation after needs
    // whitespace or punctuation before (CommonMark), or a CJK character before (* only)
    const open =
      !after ||
      (after === PUNCTUATION && (Boolean(before) || (star && isCjk(previous)))) ||
      (attentionMarkers.includes(code) && code !== ASTERISK && code !== UNDERSCORE);
    // 닫는 쪽: 앞이 문장 부호면 뒤가 공백 · 문장 부호(CommonMark)이거나 한중일 글자(* 만) / closing: punctuation before needs
    // whitespace or punctuation after (CommonMark), or a CJK character after (* only)
    const close =
      !before ||
      (before === PUNCTUATION && (Boolean(after) || (star && isCjk(code)))) ||
      (attentionMarkers.includes(previous) && previous !== ASTERISK && previous !== UNDERSCORE);

    token._open = Boolean(star ? open : open && (before || !close));
    token._close = Boolean(star ? close : close && (after || !open));

    return ok(code);
  }
}

// 이름이 'attention' 이 아니어야 아래 disable 에 걸리지 않는다. resolveAll 은 핵심과 같은 함수라 한 번만 돈다.
// Its name must not be 'attention' (the disable below would hit it). resolveAll is the core function, so it runs once.
const cjkAttention: Construct = {
  name: "ai365CjkAttention",
  tokenize: tokenizeCjkAttention,
  resolveAll: attention.resolveAll,
};

/** micromark 확장: 핵심 attention 을 끄고 한중일 친화 판을 넣는다 / Swaps the core attention for the CJK-friendly one. */
export const cjkFriendlyAttention: Extension = {
  disable: { null: ["attention"] },
  text: { [ASTERISK]: cjkAttention, [UNDERSCORE]: cjkAttention },
};

type ProcessorLike = { data(): Record<string, unknown> };

/** remark 플러그인(react-markdown 의 remarkPlugins 에 넣는다) / The remark plugin (for react-markdown's remarkPlugins). */
export function remarkCjkFriendly(this: ProcessorLike): undefined {
  const data = this.data() as { micromarkExtensions?: Extension[] };

  (data.micromarkExtensions ??= []).push(cjkFriendlyAttention);

  return undefined;
}
