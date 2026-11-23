// 답 글 ↔ OpenUI 프로그램. 서버 app/openui.py 의 strip_fences · is_program · wrap_text 와 같은 규칙이다.
// Answer text and OpenUI programs. The same rules as strip_fences, is_program and wrap_text in the server's
// app/openui.py.

const FENCE_LINE = /^\s*```[\w-]*\s*$/;

// 문장 줄 `name = ...`(예제와 같은 판정) / a statement line `name = ...` (the example's test)
const STATEMENT_LINE = /^\s*\$?[A-Za-z_][\w]*\s*=/m;

/** 모델이 ``` 펜스로 감쌌으면 펜스 줄만 지운다 / Drops ``` fence lines when the model wrapped the program in them. */
export function toProgram(text: unknown): string {
  return String(text ?? "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => !FENCE_LINE.test(line))
    .join("\n")
    .trim();
}

/** 문장 줄이 하나라도 있으면 프로그램 / A program has at least one statement line. */
export function isProgram(text: unknown): boolean {
  return STATEMENT_LINE.test(String(text ?? ""));
}

/** openui-lang 문자열 = JSON 문자열 표기 / An openui-lang string literal is a JSON string. */
export function quote(text: unknown): string {
  return JSON.stringify(text === null || text === undefined ? "" : String(text));
}

export type WrapSource = { title?: unknown; sourceName?: unknown; url?: unknown };

/**
 * 마크다운 글을 감싼 결정적 프로그램(계약 7 · 8절의 감싸기 템플릿, 서버 wrap_text 와 같은 결과: 후속 질문은 앞뒤 공백을
 * 지우고 빈 것은 뺀다, 출처 url 이 비면 url 칸을 쓰지 않는다).
 * A deterministic program around markdown text (the wrap template of contract sections 7 and 8, the same output as
 * the server's wrap_text: follow-ups are trimmed and empty ones dropped; a source without a url gets no url field):
 *
 *   root = Card([body, fu], [src1, src2])
 *   body = TextContent("<markdown>")
 *   fu = FollowUpBlock([fu1, fu2])
 *   fu1 = FollowUpItem("<text>")
 *   src1 = {title: "<title>", sourceName: "<name>", url: "<url>"}
 */
export function wrapText(markdown: unknown, sources?: WrapSource[] | null, followups?: unknown[] | null): string {
  const srcs = Array.isArray(sources) ? sources : [];
  const fus = (Array.isArray(followups) ? followups : [])
    .map((f) => (f === null || f === undefined ? "" : String(f).trim()))
    .filter(Boolean);
  const children = fus.length ? "[body, fu]" : "[body]";
  const srcRefs = srcs.map((_, i) => `src${i + 1}`).join(", ");
  const lines = [srcs.length ? `root = Card(${children}, [${srcRefs}])` : `root = Card(${children})`];

  lines.push(`body = TextContent(${quote(markdown)})`);

  if (fus.length) {
    lines.push(`fu = FollowUpBlock([${fus.map((_, i) => `fu${i + 1}`).join(", ")}])`);
    fus.forEach((text, i) => lines.push(`fu${i + 1} = FollowUpItem(${quote(text)})`));
  }

  srcs.forEach((s, i) => {
    const fields = [`title: ${quote(s?.title)}`, `sourceName: ${quote(s?.sourceName)}`];

    if (s?.url) fields.push(`url: ${quote(s.url)}`);

    lines.push(`src${i + 1} = {${fields.join(", ")}}`);
  });

  return lines.join("\n");
}

// 문자열 리터럴(큰따옴표, 백슬래시 이스케이프) / a string literal (double quotes, backslash escapes)
const STRING = /"(?:[^"\\\n]|\\.)*"/g;
const SOURCE_LINE = /^\s*src\d+\s*=/;
const URL_TEXT = /^(?:https?|ai365):\/\//i;

/**
 * 프로그램의 평문(렌더가 깨졌을 때 대신 보여 줄 글): 문자열 리터럴을 순서대로, 출처 줄과 주소는 뺀다.
 * The program's plain text (shown when rendering breaks): its string literals in order, without source lines
 * and URLs.
 */
export function plainText(program: unknown): string {
  const parts: string[] = [];

  for (const line of toProgram(program).split("\n")) {
    if (SOURCE_LINE.test(line)) continue;

    for (const match of line.matchAll(STRING)) {
      try {
        const value = JSON.parse(match[0]);

        if (typeof value === "string" && value.trim() && !URL_TEXT.test(value.trim())) parts.push(value.trim());
      } catch {
        // 잘린 리터럴 / a cut literal
      }
    }
  }

  return parts.join("\n\n");
}
