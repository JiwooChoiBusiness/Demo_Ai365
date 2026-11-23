// 인용 [n] 은 설명(TextContent)에서만 칩이 된다. 제목 · 시간 · 배지에서는 "[2]" 글자로 보이니 지운다.
// Citations [n] become chips only in descriptions (TextContent). In a title, a time or a badge they would show as
// plain "[2]", so they are dropped there.
export function withoutCitations(text: string): string {
  return text.replace(/\s*\[\d+\](\s*\[\d+\])*/g, "").trim();
}
