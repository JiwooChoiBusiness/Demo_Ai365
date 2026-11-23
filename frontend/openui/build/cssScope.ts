// @openuidev/react-ui 의 CSS 를 섬 안으로 가두는 PostCSS 플러그인. 호스트(목업) 화면은 이 CSS 의 영향을 받지 않는다.
// A PostCSS plugin that confines @openuidev/react-ui's CSS to the island; the host (mockup) page is never touched.
//
// - 모든 선택자 앞에 :is(.ai365-oui,.ai365-oui-portal) 을 붙인다(섬 안 · 포털 안). 포털 뿌리 요소(선택 목록 · 툴팁 ·
//   날짜 선택 · 차트 툴팁)는 자기 자신에게 .ai365-oui-portal 이 붙으므로 그 경우의 선택자도 하나 더 둔다.
//   Every selector gets :is(.ai365-oui,.ai365-oui-portal) in front (inside the island, inside a portal). Portal
//   roots (select lists, tooltips, the date picker, chart tooltips) carry .ai365-oui-portal themselves, so their
//   selectors get one more copy for that case.
// - :root 의 --openui-* 기본값은 .ai365-oui · .ai365-oui-portal 로 옮기고, 글꼴 "Inter" 는 섬 글꼴 변수로 바꾼다.
//   The --openui-* defaults on :root move to .ai365-oui and .ai365-oui-portal, and the "Inter" font becomes the
//   island's font variable.
// - 어두운 테마 규칙은 지운다(데모는 밝은 테마 고정). / Dark theme rules are dropped (the demo is light only).
// - @keyframes 이름에 ai365oui- 를 붙인다(호스트에도 fadeIn · slideDown 이 있어 덮어쓰게 된다).
//   @keyframes names get an ai365oui- prefix (the host has fadeIn and slideDown too, which would be overwritten).
// - 섬에 나올 수 없는 컴포넌트(뺀 컴포넌트 · 에이전트 화면)의 CSS 를 덜어 낸다: 그 파일들에만 나오는 클래스를 선택자마다
//   하나 이상 요구하는 규칙만 지우므로, 남은 컴포넌트에 걸리던 규칙은 그대로다.
//   CSS of components that can never appear in the island (the dropped components, the agent screens) is pruned:
//   only rules whose every selector needs a class found in those files alone are removed, so no rule that could
//   match a kept component goes.
import fs from "node:fs";
import path from "node:path";
import postcss from "postcss";
import type { AtRule, Declaration, Plugin, Root, Rule } from "postcss";

export const ISLAND = ".ai365-oui";
export const PORTAL = ".ai365-oui-portal";
const SCOPE = `:is(${ISLAND},${PORTAL})`;
const KEYFRAME_PREFIX = "ai365oui-";

/** 섬에 나올 수 없는 컴포넌트의 CSS 파일(react-ui dist/styles) / CSS files of components the island never shows. */
const UNUSED_STYLE_FILES = [
  "agentInterface", "toolCall", "toolResult", "modelSwitcher", "editableTable", "imageGallery", "imageBlock", "image",
  "imageText", "imageTextLarge", "contextCardBlock", "snippetCardBlock", "visualCardBlock", "compositeCardBlock",
  "overviewCardBlock", "shared", "metricIndicator", "iconText", "textBlock",
];

const CLASS_NAME = /\.(-?[_a-zA-Z][\w-]*)/g;

function classesOf(selector: string): string[] {
  return [...selector.matchAll(CLASS_NAME)].map((m) => m[1]);
}

/** 쓰지 않는 파일들에만 나오는 클래스 / Classes that appear only in the unused files. */
function unusedOnlyClasses(stylesDir: string): Set<string> {
  const unused = new Set<string>();
  const kept = new Set<string>();

  for (const name of fs.readdirSync(stylesDir)) {
    if (!name.endsWith(".css") || name === "index.css" || name === "openui-defaults.css") continue;

    const target = UNUSED_STYLE_FILES.includes(name.replace(/\.css$/, "")) ? unused : kept;

    postcss.parse(fs.readFileSync(path.join(stylesDir, name), "utf8")).walkRules((rule) => {
      for (const selector of rule.selectors) for (const cls of classesOf(selector)) target.add(cls);
    });
  }

  for (const cls of kept) unused.delete(cls);

  return unused;
}

/** 지운 규칙만 쓰던 @keyframes 도 지운다 / Drops @keyframes that only the removed rules used. */
function dropUnusedKeyframes(root: Root) {
  const used = new Set<string>();

  root.walkDecls(/(^|-)animation(-name)?$/i, (decl) => {
    for (const token of decl.value.split(/[\s,]+/)) used.add(token);
  });
  root.walkAtRules(/keyframes$/i, (at) => {
    if (!used.has(at.params.trim())) at.remove();
  });
}

function dropEmptyAtRules(root: Root) {
  root.walkAtRules((at) => {
    if (at.nodes && at.nodes.length === 0) at.remove();
  });
}

/** portalThemeClassName 을 받는 포털 뿌리 요소의 클래스 / Classes of the portal roots that get portalThemeClassName. */
const PORTAL_ROOTS = [
  "openui-select-content",
  "openui-tooltip-content",
  "openui-citation-tooltip",
  "openui-date-picker-renderer-floating-content",
  "openui-portal-tooltip",
  "openui-modal-root",
];

const VENDOR_FILE = /[\\/]@openuidev[\\/]react-ui[\\/]/;

/** 선택자의 첫 복합 선택자가 끝나는 곳 / Where a selector's first compound selector ends. */
function firstCompoundEnd(selector: string): number {
  let depth = 0;
  let quote = "";

  for (let i = 0; i < selector.length; i++) {
    const c = selector[i];

    if (quote) {
      if (c === "\\") i++;
      else if (c === quote) quote = "";
      continue;
    }

    if (c === '"' || c === "'") quote = c;
    else if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") depth--;
    else if (depth === 0 && (c === " " || c === ">" || c === "+" || c === "~" || c === "\n" || c === "\t")) {
      return i;
    }
  }

  return selector.length;
}

/** 복합 선택자에 클래스를 붙인다(가상 요소 앞) / Adds a class to a compound selector (before any pseudo-element). */
function addClass(compound: string, cls: string): string {
  const pseudo = compound.indexOf("::");

  return pseudo >= 0 ? compound.slice(0, pseudo) + cls + compound.slice(pseudo) : compound + cls;
}

function hasPortalRoot(compound: string): boolean {
  return PORTAL_ROOTS.some((name) => new RegExp(`\\.${name}(?![\\w-])`).test(compound));
}

/** 선택자 하나를 섬 범위로 / One selector, scoped to the island. */
export function scopeSelector(selector: string): string[] {
  const s = selector.trim();

  if (!s) return [];

  if (/^(html|body|:root)\b/.test(s)) {
    const rest = s.replace(/^(html|body|:root)/, "");

    return [`${ISLAND}${rest}`, `${PORTAL}${rest}`];
  }

  const out = [`${SCOPE} ${s}`];
  const end = firstCompoundEnd(s);
  const first = s.slice(0, end);

  if (hasPortalRoot(first)) out.push(addClass(first, PORTAL) + s.slice(end));

  return out;
}

function inKeyframes(rule: Rule): boolean {
  const parent = rule.parent as AtRule | undefined;

  return !!parent && parent.type === "atrule" && /keyframes$/i.test(parent.name);
}

function renameAnimations(decl: Declaration, names: Set<string>) {
  decl.value = decl.value
    .split(",")
    .map((part) =>
      part
        .split(/(\s+)/)
        .map((token) => (names.has(token) ? KEYFRAME_PREFIX + token : token))
        .join(""),
    )
    .join(",");
}

/** 섬 범위 PostCSS 플러그인 / The island scoping PostCSS plugin. */
export function cssScope(): Plugin {
  let unusedOnly: Set<string> | null = null;

  return {
    postcssPlugin: "ai365-oui-scope",
    Once(root: Root) {
      const file = root.source?.input.file ?? "";

      if (!VENDOR_FILE.test(file)) return;

      // 1. 어두운 테마 / dark theme
      root.walkAtRules("media", (at) => {
        if (/prefers-color-scheme\s*:\s*dark/i.test(at.params)) at.remove();
      });
      root.walkRules((rule) => {
        if (/data-openui-theme\s*=\s*"?dark/.test(rule.selector) || /:root:not\(/.test(rule.selector)) {
          rule.remove();
        }
      });

      // 2. 섬에 나올 수 없는 컴포넌트의 규칙 / rules of components the island never shows
      unusedOnly ??= unusedOnlyClasses(path.join(file.replace(/[\\/]dist[\\/].*$/, ""), "dist", "styles"));

      const unused = unusedOnly;

      root.walkRules((rule) => {
        if (inKeyframes(rule)) return;

        if (rule.selectors.every((selector) => classesOf(selector).some((cls) => unused.has(cls)))) rule.remove();
      });
      dropUnusedKeyframes(root);
      dropEmptyAtRules(root);

      // 3. @keyframes 이름 / keyframe names
      const names = new Set<string>();

      root.walkAtRules(/keyframes$/i, (at) => {
        names.add(at.params.trim());
        at.params = KEYFRAME_PREFIX + at.params.trim();
      });
      root.walkDecls(/(^|-)animation(-name)?$/i, (decl) => renameAnimations(decl, names));

      // 4. :root 기본값과 글꼴 / the :root defaults and the font
      root.walkRules((rule) => {
        if (rule.selector.trim() !== ":root") return;

        rule.walkDecls((decl) => {
          decl.value = decl.value.replace(/"Inter",\s*sans-serif/g, "var(--ai365-oui-font)");
        });
      });

      // 5. 선택자 범위 / selector scoping
      root.walkRules((rule) => {
        if (inKeyframes(rule)) return;

        rule.selectors = rule.selectors.flatMap(scopeSelector);
      });
    },
  };
}

cssScope.postcss = true;
