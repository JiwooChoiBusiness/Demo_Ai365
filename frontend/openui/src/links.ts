// 섬 안 링크 규칙. 출처 칩 · 인용 · 마크다운 링크 · @OpenUrl · OpenUI 안의 window.open 모두 여기로 온다.
// - ai365://…   → 기본 동작을 막고 opts.onLink(url, el)
// - http(s)://… → window.open(url, "_blank", "noopener")
// - 그 밖       → 무시
// The island's link rule. Source chips, citations, markdown links, @OpenUrl and OpenUI's own window.open all end
// up here:
// - ai365://…   → the default is prevented and opts.onLink(url, el) is called
// - http(s)://… → window.open(url, "_blank", "noopener")
// - anything else → ignored

export type LinkContext = {
  el: HTMLElement;
  onLink?: (url: string, el: HTMLElement) => void;
};

export type LinkKind = "internal" | "external" | "ignored";

const INTERNAL = /^ai365:\/\//i;
const EXTERNAL = /^https?:\/\//i;

export function linkKind(url: unknown): LinkKind {
  if (typeof url !== "string") return "ignored";

  const value = url.trim();

  if (INTERNAL.test(value)) return "internal";
  if (EXTERNAL.test(value)) return "external";

  return "ignored";
}

/** 링크 하나를 규칙대로 연다 / Opens one link by the rule. */
export function followLink(url: unknown, ctx: LinkContext | null): LinkKind {
  const kind = linkKind(url);
  const value = typeof url === "string" ? url.trim() : "";

  if (kind === "internal") {
    ctx?.onLink?.(value, ctx.el);
  } else if (kind === "external") {
    window.open(value, "_blank", "noopener");
  }

  return kind;
}

// OpenUI 안의 window.open(safeOpenUrl)은 어느 섬에서 눌렸는지 모른다. 섬 뿌리의 캡처 단계 처리기(React 합성 이벤트라
// 포털 안 클릭도 지나간다)가 그 순간의 섬을 적어 둔다.
// OpenUI's own window.open (safeOpenUrl) does not know which island was clicked. The island root's capture-phase
// handler (a React synthetic event, so clicks inside its portals pass through too) records the island of the moment.
let current: LinkContext | null = null;
let last: LinkContext | null = null;

/** 섬 안 이벤트가 시작될 때 / When an event inside an island starts. */
export function enterIsland(ctx: LinkContext) {
  current = ctx;
  last = ctx;

  // 이벤트가 끝나면 비운다(처리기가 전파를 멈춰도) / cleared once the event is over (even if propagation stops)
  setTimeout(() => {
    if (current === ctx) current = null;
  }, 0);
}

/** 섬이 사라질 때 / When an island goes away. */
export function forgetIsland(el: HTMLElement) {
  if (current?.el === el) current = null;
  if (last?.el === el) last = null;
}

/** 빌드 때 고친 safeOpenUrl 이 부른다 / Called by the safeOpenUrl patched at build time. */
export function openFromVendor(url: unknown): null {
  followLink(url, current ?? last);

  return null;
}
