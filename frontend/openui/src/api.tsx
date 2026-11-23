// 섬 본체: window.AI365_OpenUI 를 세운다(계약 4 · 7 · 8절). 빌드는 이 모듈과 그 정적 의존(React 포함)을
// 내용 해시 이름의 청크 static/openui/chunks/main-<해시>.js 하나로 묶고, 진입점 openui.js 는 다시 내보내기만 한다
// (vite.config.ts 의 manualChunks). 그래서 화면이 openui.js?v=<버전> 처럼 쿼리를 붙여 불러도 지연 청크(mermaid ·
// 아이콘 묶음)는 같은 main 청크 주소를 가져오고, 본체는 한 번만 평가된다.
// The island core: sets window.AI365_OpenUI (contract sections 4, 7 and 8). The build puts this module and its
// static dependencies (React included) into one content-hashed chunk, static/openui/chunks/main-<hash>.js, and the
// entry openui.js only re-exports it (manualChunks in vite.config.ts). So even when the page loads the entry with a
// query (openui.js?v=<version>), the lazy chunks (mermaid, the icon set) import the same main chunk URL, and the core
// is evaluated exactly once.
//
//   render(el, program, opts)  el 안에 그린다(같은 el 이면 갱신) / renders into el (updates on the same el)
//   unmount(el)                뿌리를 내린다 / unmounts the root
//   toProgram(text)            ``` 펜스 줄을 지운다 / drops ``` fence lines
//   isProgram(text)            문장 줄이 하나라도 있나 / whether there is a statement line
//   wrapText(md, sources?, followups?)  서버 wrap_text 와 같은 감싼 프로그램 / the server wrap_text's program
import "@openuidev/react-ui/components.css";
import "./styles/island.css";

import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";

import { setCurrentLang, toLang } from "./i18n";
import { Island, type IslandOptions } from "./Island";
import { forgetIsland } from "./links";
import { isProgram, toProgram, wrapText } from "./program";

declare const __AI365_OUI_VERSION__: string;

// 본체가 평가된 횟수(정상은 1). 2 이상이면 같은 페이지에 섬 두 벌이 있다는 뜻이라 경고한다.
// How many times the core was evaluated (1 when healthy). Two or more means two copies of the island on one page,
// which is warned about.
const LOADS = Symbol.for("ai365.openui.loads");
const counter = globalThis as unknown as Record<symbol, number>;

counter[LOADS] = (counter[LOADS] ?? 0) + 1;

if (counter[LOADS] > 1) console.warn("[AI365 OpenUI] the island bundle was evaluated more than once");

const roots = new WeakMap<Element, Root>();

function isElement(value: unknown): value is HTMLElement {
  return typeof value === "object" && value !== null && (value as Node).nodeType === 1;
}

/** el 안에 프로그램(또는 마크다운)을 그린다 / Renders a program (or markdown) into el. */
function render(el: HTMLElement, program: unknown, opts: IslandOptions = {}): void {
  if (!isElement(el)) throw new TypeError("AI365_OpenUI.render: el must be an element");

  el.classList.add("ai365-oui");
  setCurrentLang(toLang(opts?.lang));

  let root = roots.get(el);

  if (!root) {
    root = createRoot(el);
    roots.set(el, root);
  }

  const view = <Island el={el} program={program === null || program === undefined ? "" : String(program)} opts={opts ?? {}} />;
  const target = root;

  // 돌아온 뒤엔 화면이 이미 그려져 있다(지연 청크 mermaid · 아이콘 묶음은 나중에) / the DOM is current on return
  // (lazy chunks such as mermaid and the icon set arrive later)
  flushSync(() => target.render(view));
}

/** el 의 뿌리를 내린다 / Unmounts el's root. */
function unmount(el: HTMLElement): void {
  if (!isElement(el)) return;

  const root = roots.get(el);

  if (root) {
    roots.delete(el);
    root.unmount();
  }

  forgetIsland(el);
}

export const version: string = __AI365_OUI_VERSION__;

const api = { version, render, unmount, toProgram, isProgram, wrapText };

declare global {
  interface Window {
    AI365_OpenUI?: typeof api;
  }
}

if (typeof window !== "undefined") window.AI365_OpenUI = api;

export { render, unmount, toProgram, isProgram, wrapText };
export default api;
