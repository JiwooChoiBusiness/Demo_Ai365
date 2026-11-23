// rehype-katex 대신(vite.config.ts 의 별칭). OpenUI 의 TextContent 는 답마다 KaTeX(약 270KB)를 동적으로 불러오지만
// KaTeX CSS 가 없어 수식이 깨져 보인다. 그래서 끈다: $$...$$ 는 math 코드 블록으로 남는다.
// Stands in for rehype-katex (an alias in vite.config.ts). OpenUI's TextContent loads KaTeX (about 270KB)
// dynamically for every answer, but without KaTeX's CSS the math renders broken, so it is off: $$...$$ stays a
// math code block.
export default function rehypeKatexOff() {
  return undefined;
}
