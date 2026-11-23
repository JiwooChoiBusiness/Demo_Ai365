// 맞춤 컴포넌트가 빌려 쓰는 OpenUI 기본 컴포넌트의 렌더러(genui-lib 번들 것). @openuidev/react-ui 의 본 번들을 따로
// 가져오지 않으니 출처 컨텍스트가 하나뿐이다: PlaceCard 설명의 [n] 도 루트 Card 의 출처를 읽는다.
// The renderers of OpenUI built-ins that our components borrow (the genui-lib bundle's). The main
// @openuidev/react-ui bundle is never imported, so there is a single sources context: a [n] in a PlaceCard
// description reads the root Card's sources too.
import type { ComponentRenderer } from "@openuidev/react-lang";
import { openuiChatLibrary } from "@openuidev/react-ui/genui-lib";

const builtins = openuiChatLibrary.components;

/** TextContent(마크다운 · [n] 인용) / TextContent (markdown, [n] citations). */
export const TextContentView = builtins.TextContent.component as ComponentRenderer<{ text: string; size?: string }>;

/** Tag(배지) / Tag (a badge). */
export const TagView = builtins.Tag.component as ComponentRenderer<{ text: string; size?: string; variant?: string }>;

/** CodeBlock(구문 강조) / CodeBlock (syntax highlighting). */
export const CodeBlockView = builtins.CodeBlock.component as ComponentRenderer<{ language: string; codeString: string }>;

/** 이 렌더러들은 자식 노드를 그리지 않는다 / These renderers draw no child nodes. */
export const renderNothing = (): null => null;
