// 빌드 때 @openuidev/react-ui 의 genui-lib 번들(dist/genui-lib/index.mjs)에 고치는 몇 곳.
// 버전이 package.json 에 고정돼 있어 바꿀 문자열은 늘 같다. 하나라도 정확히 기대한 횟수만큼 찾지 못하면
// 빌드를 멈춘다(버전을 올렸는데 조용히 빠지는 일이 없게).
//
// Build-time edits to @openuidev/react-ui's genui-lib bundle (dist/genui-lib/index.mjs). The version is pinned
// in package.json, so the strings to change are always the same. If any is not found exactly the expected number
// of times the build stops, so a version bump can never skip one silently.
//
// 고치는 것 / What changes:
// - safeOpenUrl: window.open 대신 섬의 링크 규칙(ai365:// → onLink, http(s) → 새 창 noopener)
//   / the island's link rule instead of window.open (ai365:// → onLink, http(s) → a new tab with noopener)
// - getFaviconUrl: http(s) 출처만 구글 파비콘, 사내 · 로컬 · 데이터(ai365://kn · local · data)와 url 없는 그룹웨어 출처는
//   섬이 그리는 아이콘 표식, 그 밖은 빈 값 = ai365:// 와 url 없는 출처는 네트워크 요청 없음
//   / Google favicons for http(s) sources only, the island's icon marker for internal, local and data sources
//   (ai365://kn, local, data) and url-less groupware sources, nothing otherwise, so neither ai365:// nor a url-less
//   source ever makes a request
// - 출처 아이콘: 출처 띠 카드의 로고 칸에 사내 · 로컬 문서 · 데이터 · 그룹웨어 아이콘, 띠 카드에 제목 툴팁
//   / source icons: the internal, local, data and groupware icons in the Sources strip cards' logo slots, and a title
//   tooltip on strip cards
// - 본문 인용 [n] = 번호 칩(2026-10-29, src/vendor/citationChips.tsx): TextContentCitation 이 지구 단추 + 출처 말풍선(Citation)
//   대신 [n] 마다 위첨자 번호 칩을 그린다(번호 = 출처 목록 위치 n, title, 누르면 그 출처를 바로 연다)
//   / inline [n] = number chips (2026-10-29, src/vendor/citationChips.tsx): TextContentCitation draws a superscript number
//   chip per [n] (the number = position n in the sources list, a title, a click opens that source) instead of the globe
//   button and its sources popover (Citation)
// - remarkCitations 의 정규식: [n] 뒤 공백을 먹지 않고(뒤 글에 남는다) 쉼표(, ， 、)로 이은 나열 "[1], [2], [3]" 도 한 묶음으로 본다.
//   칩 자리 다듬기(src/vendor/citationPlacement.ts)가 앞 공백을 지워도 "[1] 그리고" 의 띄어쓰기가 남고, 나열은 "¹²³" 이 된다
//   / remarkCitations' regex no longer swallows the whitespace after [n] (it stays in the following text) and treats a
//   comma-joined list "[1], [2], [3]" (, ， 、) as one group, so "[1] next" keeps its space when the chip placement
//   (src/vendor/citationPlacement.ts) removes the space before, and a list becomes "¹²³"
// - MarkDownRenderer: react-markdown 의 urlTransform 에 ai365: 를 허용(기본 변환은 이 주소를 지운다), 모든 마크다운 자리에 한중일
//   친화 강조(src/vendor/cjkEmphasis.ts: `**55%**로` 가 굵게) / allow ai365: in react-markdown's urlTransform (the default
//   one blanks such links), and CJK-friendly emphasis on every markdown surface (src/vendor/cjkEmphasis.ts)
// - 인용 칩: Callout · TextCallout 설명, StepsItem 설명, ListItem 부제의 [n] 도 TextContent 와 같은 칩(누르는 목록 줄은 [n] 을
//   지운다) / citation chips: [n] in Callout and TextCallout descriptions, StepsItem details and ListItem subtitles
//   becomes the same chip as in TextContent (a clickable list row drops the [n] instead)
// - ThemeContext 기본값: 포털 클래스 ai365-oui-portal · 데모 차트 색(밝은 테마 고정)
//   / the default ThemeContext: portal class ai365-oui-portal and the demo chart palette (light only)
// - 화면 글자(출처 · 관련 질문 · 데이터 없음 · 더 보기 · 날짜 · 월 선택 · 입력 검증 문구 · 복사 단추 이름)를 opts.lang 으로
//   / on-screen labels (Sources, Related Queries, No data, Show more, the date and month pickers, validation
//     messages, the copy button's name) follow opts.lang
// - useId: crypto.randomUUID 가 없는 문맥(사내망 http)에서도 / useId works where crypto.randomUUID is missing (intranet http)
// - Table: Col 의 type "number" 열은 머리 · 칸을 오른쪽 정렬하고 큰 수에 천 단위 쉼표(hooks.tsx 의 numberColumn)
//   / Table: a Col of type "number" aligns its header and cells right and gets thousands separators for large numbers
//     (numberColumn in hooks.tsx)
import type { Plugin } from "vite";

/** 섬 쪽 훅 모듈을 가리키는 별칭 / The alias of the island's hook module. */
export const HOOKS_ALIAS = "ai365-oui-vendor-hooks";

type Patch = { name: string; find: string; replace: string; count: number };

const PATCHES: Patch[] = [
  {
    name: "safeOpenUrl → island link rule",
    find: "return window.open(safe, target, features);",
    replace: "return __ai365oui.openUrl(safe, target, features);",
    count: 1,
  },
  {
    // url 이 없는 출처(그룹웨어)도 섬의 규칙으로(원래는 먼저 "" 를 돌려 지구 아이콘이 된다)
    // url-less sources (groupware) go through the island's rule too (originally an early "" gave them the globe)
    name: "getFaviconUrl → http(s) only",
    find: 'if (!url) return "";\n\t\treturn `https://www.google.com/s2/favicons?sz=128&domain=${new URL(url).hostname}`;',
    replace: "return __ai365oui.faviconUrl(url);",
    count: 1,
  },
  {
    // 출처 로고 칸(띠 카드): 사내 · 로컬 문서 표식이면 문서 아이콘(훅은 그대로 위에서 다 부른다)
    // source logo slot (strip cards): the document icon for a document marker (all hooks still run above)
    name: "source logo: document icon",
    find:
      '\tif (imageError || !url) return /* @__PURE__ */ jsx(IconWrapper, {\n\t\tname: "globe",\n\t\tsize: Math.max(height, width)\n\t});',
    replace:
      '\tconst ai365Doc = __ai365oui.docKind(url);\n\tif (ai365Doc) return /* @__PURE__ */ jsx(__ai365oui.DocIcon, {\n\t\tkind: ai365Doc,\n\t\tsize: Math.max(height, width)\n\t});\n\tif (imageError || !url) return /* @__PURE__ */ jsx(IconWrapper, {\n\t\tname: "globe",\n\t\tsize: Math.max(height, width)\n\t});',
    count: 1,
  },
  {
    // 본문 인용 [n] = 번호 칩(2026-10-29): 출처 말풍선(Citation) 대신 [n] 마다 번호 칩. 번호 n = 루트 Card 출처 목록의 n 번째 =
    // 출처 띠의 n 번째 카드(띠도 같은 목록을 순서대로 그린다). 누르면 띠 카드 · 옛 말풍선 줄과 같은 openSourceInNewTab 으로 연다.
    // 출처가 없는 카드면 그대로 null(위 줄), 목록에 없는 번호는 칩이 없다.
    // inline [n] = number chips (2026-10-29): one number chip per [n] instead of the sources popover (Citation). The number n
    // = the nth source of the root Card = the nth card of the Sources strip (the strip draws the same list in order). A click
    // opens it through the same openSourceInNewTab as a strip card or an old popover row. A card without sources still
    // returns null (the line above); a number not in the list gets no chip.
    name: "citation number chips",
    find:
      '\tconst relevantSources = indicesString.split(",").map(Number).map((idx) => sources[idx - 1]).filter((source) => source !== void 0).filter((source) => source.sourceName && source.title && source.sourceName.trim() !== "" && source.title.trim() !== "");\n\tif (relevantSources.length === 0) return null;\n\treturn /* @__PURE__ */ jsx(Citation, { sources: relevantSources });',
    replace:
      "\treturn /* @__PURE__ */ jsx(__ai365oui.CitationNumbers, {\n\t\tindices: indicesString,\n\t\tsources,\n\t\topen: openSourceInNewTab\n\t});",
    count: 1,
  },
  {
    // remarkCitations 의 인용 묶음 정규식 두 가지(2026-10-29):
    // ① 묶음 뒤의 공백까지 먹던 것을 그만둔다. 공백은 뒤 글에 남아, 칩 자리 다듬기(src/vendor/citationPlacement.ts)가 앞 공백을
    //    지워도 "알립니다 [1] 그리고" → "알립니다¹ 그리고" 가 된다.
    // ② 쉼표(, ， 、)와 공백만으로 이어진 나열도 한 묶음이다: "문서 [1], [2], [3]에" → "문서¹²³에"(구분 쉼표는 묶음 안이라 사라지고,
    //    번호는 아래 numberExtractorRegex 가 묶음 안의 [n] 을 모두 뽑는다). 뒤에 [n] 이 없는 쉼표는 묶음에 들지 않아
    //    "문서 [1], 그리고" 는 그대로 "문서,¹ 그리고" 가 된다.
    // Two changes to remarkCitations' citation-group regex (2026-10-29):
    // (1) it stops swallowing the whitespace after a group, which stays in the following text, so with the chip placement
    //     (src/vendor/citationPlacement.ts) removing the space before, "알립니다 [1] 그리고" becomes "알립니다¹ 그리고";
    // (2) a list joined only by commas (, ， 、) and whitespace is one group too: "문서 [1], [2], [3]에" → "문서¹²³에" (the
    //     separating commas are inside the group and go away; numberExtractorRegex below pulls every [n] out of the group).
    //     A comma not followed by [n] stays out of the group, so "문서 [1], 그리고" still becomes "문서,¹ 그리고".
    name: "citation regex: following space kept, comma lists grouped",
    find: "const customComponentRegex = /(\\[\\d+\\]\\s*)+/g;",
    replace: "const customComponentRegex = /\\[\\d+\\](?:\\s*[,，、]?\\s*\\[\\d+\\])*/g;",
    count: 1,
  },
  {
    // 출처 띠 카드에 마우스를 올리면 출처 제목(같은 아이콘끼리 구별) / hovering a strip card shows the source title
    name: "source card title",
    find: '\t\trole: "button",\n\t\ttabIndex: 0,\n\t\t"data-source-id": sourceId,',
    replace: '\t\trole: "button",\n\t\ttabIndex: 0,\n\t\t"data-source-id": sourceId,\n\t\ttitle,',
    count: 1,
  },
  {
    // 모든 마크다운 자리가 이 렌더러를 거친다: ai365: 링크 허용 + 한중일 친화 강조(**55%**로)
    // every markdown surface goes through this renderer: ai365: links allowed, plus CJK-friendly emphasis (**55%**로)
    name: "MarkDownRenderer urlTransform and CJK emphasis",
    find: "const markdownProps = {\n\t\t...props.options,",
    replace:
      "const markdownProps = {\n\t\turlTransform: __ai365oui.urlTransform,\n\t\t...props.options,\n\t\tremarkPlugins: __ai365oui.remarkPlugins(props.options?.remarkPlugins),",
    count: 1,
  },
  {
    // Callout 설명의 [n] 을 TextContent 와 같은 인용 칩으로(루트 Card 의 출처) / [n] in a Callout description becomes the
    // same citation chip as in TextContent (the root Card's sources)
    name: "Callout description citations",
    find: "description: /* @__PURE__ */ jsx(MarkDownRenderer$1, { textMarkdown: props.description }),",
    replace:
      "description: /* @__PURE__ */ jsx(MarkDownRenderer$1, { textMarkdown: props.description, options: { remarkPlugins: [remarkCitations], components: { span: TextContentCitation } } }),",
    count: 1,
  },
  {
    name: "Steps details citations",
    find: 'const detailsContent = typeof details === "string" ? /* @__PURE__ */ jsx(MarkDownRenderer$1, { textMarkdown: details }) : renderNode(details);',
    replace:
      'const detailsContent = typeof details === "string" ? /* @__PURE__ */ jsx(MarkDownRenderer$1, { textMarkdown: details, options: { remarkPlugins: [remarkCitations], components: { span: TextContentCitation } } }) : renderNode(details);',
    count: 1,
  },
  {
    // TextCallout 설명은 원래 맨 글자: 인라인 마크다운(굵게 · [n] 칩)으로 / a TextCallout description was plain text; now
    // inline markdown (bold, [n] chips)
    name: "TextCallout description markdown and citations",
    find: "component: ({ props }) => /* @__PURE__ */ jsx(TextCallout$1, {\n\t\tvariant: props.variant,\n\t\ttitle: props.title,\n\t\tdescription: props.description\n\t})",
    replace:
      "component: ({ props }) => /* @__PURE__ */ jsx(TextCallout$1, {\n\t\tvariant: props.variant,\n\t\ttitle: props.title,\n\t\tdescription: props.description ? /* @__PURE__ */ jsx(InlineMarkdownRenderer, { content: String(props.description) }) : props.description\n\t})",
    count: 1,
  },
  {
    // ListItem 부제: 누르지 않는 줄은 인라인 마크다운(굵게 · [n] 칩), 누르면 질문을 보내는 줄은 [n] 을 지운 글(칩을 누르면 줄
    // 동작까지 불린다) / a ListItem subtitle: inline markdown (bold, [n] chips) on a row without an action; on a row that
    // sends a question, plain text without [n] (a chip click would fire the row's action too)
    name: "ListItem subtitle citations",
    find: "return /* @__PURE__ */ jsx(ListItem$1, {\n\t\t\t\t\ttitle,\n\t\t\t\t\tsubtitle,\n\t\t\t\t\tlistHasSubtitle,",
    replace:
      "return /* @__PURE__ */ jsx(ListItem$1, {\n\t\t\t\t\ttitle,\n\t\t\t\t\tsubtitle: subtitle ? (hasAction ? __ai365oui.stripCitations(subtitle) : /* @__PURE__ */ jsx(InlineMarkdownRenderer, { content: subtitle })) : void 0,\n\t\t\t\t\tlistHasSubtitle,",
    count: 1,
  },
  {
    name: "ThemeContext default",
    find:
      'const ThemeContext = createContext({\n\ttheme: defaultLightTheme,\n\tmode: "light",\n\tportalThemeClassName: ""\n});',
    replace:
      'const ThemeContext = createContext({\n\ttheme: __ai365oui.theme(defaultLightTheme),\n\tmode: "light",\n\tportalThemeClassName: __ai365oui.PORTAL_CLASS\n});',
    count: 1,
  },
  {
    // crypto.randomUUID 는 보안 문맥(HTTPS · localhost)에만 있다. 사내망 http 주소로 열면 인용 툴팁이 깨진다.
    // crypto.randomUUID exists only in secure contexts (HTTPS, localhost); over a plain-http intranet address the
    // citation tooltips would crash.
    name: "useId without crypto.randomUUID",
    find: "return useMemo(() => crypto.randomUUID(), []);",
    replace: "return useMemo(() => __ai365oui.uuid(), []);",
    count: 1,
  },
  {
    name: "label Sources",
    find: 'children: "Sources"',
    replace: 'children: /* @__PURE__ */ jsx(__ai365oui.Label, { k: "Sources" })',
    count: 1,
  },
  {
    name: "label Related Queries",
    find: 'children: "Related Queries"',
    replace: 'children: /* @__PURE__ */ jsx(__ai365oui.Label, { k: "Related Queries" })',
    count: 1,
  },
  {
    name: "label No data available",
    find: 'children: "No data available"',
    replace: 'children: /* @__PURE__ */ jsx(__ai365oui.Label, { k: "No data available" })',
    count: 4,
  },
  {
    name: "label Show more / Show less",
    find: 'children: showAll ? "Show less" : "Show more"',
    replace: 'children: /* @__PURE__ */ jsx(__ai365oui.Label, { k: showAll ? "Show less" : "Show more" })',
    count: 1,
  },
  {
    name: "placeholder Select a month",
    find: 'placeholder: "Select a month"',
    replace: 'placeholder: __ai365oui.tr("Select a month")',
    count: 2,
  },
  {
    name: "date picker placeholder (range)",
    find: 'return "Select a range";',
    replace: 'return __ai365oui.tr("Select a range");',
    count: 2,
  },
  {
    name: "date picker placeholder (single)",
    find: 'return "Select a date";',
    replace: 'return __ai365oui.tr("Select a date");',
    count: 1,
  },
  {
    name: "form validation message",
    find: "children: [/* @__PURE__ */ jsx(AlertCircle, { size: 14 }), error]",
    replace: "children: [/* @__PURE__ */ jsx(AlertCircle, { size: 14 }), /* @__PURE__ */ jsx(__ai365oui.Message, { m: error })]",
    count: 1,
  },
  {
    name: "copy button name",
    find: '"aria-label": copied ? "Copied to clipboard" : "Copy code"',
    replace: '"aria-label": __ai365oui.tr(copied ? "Copied to clipboard" : "Copy code")',
    count: 1,
  },
  {
    // 표 열 정의에 "number" 열의 수 모양 · 정렬을 더한다(계약 9.4절 Col("매출액", d1top.c2, "number"))
    // the Table column definitions get the number shape and alignment of "number" columns (contract section 9.4)
    name: "Table number columns",
    find: "data: asArray(c.props?.data ?? [])",
    replace:
      "data: __ai365oui.numberColumn(asArray(c.props?.data ?? []), c.props?.type),\n\t\t\talign: __ai365oui.numberAlign(c.props?.type)",
    count: 1,
  },
  {
    name: "Table number column header alignment",
    find: "jsx(TableHead, { children: c.label }, i)",
    replace: "jsx(TableHead, { align: c.align, children: c.label }, i)",
    count: 1,
  },
  {
    name: "Table number cell alignment",
    find: 'jsx(TableCell, { children: typeof cell === "object" && cell !== null ? renderNode(cell) : String(cell ?? "") }, ci)',
    replace:
      'jsx(TableCell, { align: col.align, children: typeof cell === "object" && cell !== null ? renderNode(cell) : String(cell ?? "") }, ci)',
    count: 1,
  },
];

const TARGET = "/@openuidev/react-ui/dist/genui-lib/index.mjs";

function occurrences(text: string, part: string): number {
  return text.split(part).length - 1;
}

const NODE_ENV_BRACKETS = /process\.env\[\s*["']NODE_ENV["']\s*\]/g;

/**
 * define 은 process.env.NODE_ENV(점 표기)만 바꾼다. react-lang 은 process.env["NODE_ENV"] 로 써서 그대로 남으면
 * 브라우저에서 "process is not defined" 로 멈춘다. 호스트 전역에 process 를 만들지 않고 그 자리만 "production" 으로.
 * define replaces process.env.NODE_ENV (dot notation) only. react-lang writes process.env["NODE_ENV"], which would
 * stop the browser with "process is not defined". That spot alone becomes "production"; no global process is created
 * on the host.
 */
export function nodeEnvBrackets(): Plugin {
  return {
    name: "ai365-oui-node-env-brackets",
    enforce: "pre",
    transform(code) {
      if (!NODE_ENV_BRACKETS.test(code)) return null;

      NODE_ENV_BRACKETS.lastIndex = 0;

      return { code: code.replace(NODE_ENV_BRACKETS, '"production"'), map: null };
    },
  };
}

/** genui-lib 번들을 고치는 Vite 플러그인 / The Vite plugin that edits the genui-lib bundle. */
export function vendorPatches(): Plugin {
  let patched = false;

  return {
    name: "ai365-oui-vendor-patches",
    enforce: "pre",
    transform(code, id) {
      const file = id.split("?")[0].replace(/\\/g, "/");

      if (!file.endsWith(TARGET)) return null;

      let out = code;

      for (const patch of PATCHES) {
        const found = occurrences(out, patch.find);

        if (found !== patch.count) {
          this.error(`vendor patch "${patch.name}": expected ${patch.count}, found ${found}`);
        }

        out = out.split(patch.find).join(patch.replace);
      }

      patched = true;

      return { code: `import * as __ai365oui from "${HOOKS_ALIAS}";\n${out}`, map: null };
    },
    buildEnd(error) {
      // 번들에 genui-lib 이 들어갔는데 고치지 못했으면 실패 / fail when genui-lib was bundled unpatched
      if (!error && !patched) this.error("vendor patches were never applied (genui-lib not bundled?)");
    },
  };
}
