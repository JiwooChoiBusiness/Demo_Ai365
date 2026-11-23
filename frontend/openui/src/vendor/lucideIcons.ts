// lucide-react/dynamicIconImports.mjs 대신(vite.config.ts 의 별칭). 원본은 아이콘 1,912개를 하나씩 동적 import 해
// 청크가 1,912개 생긴다. 여기서는 자주 쓰는 셋(지구 · 원 · 원 점: 출처 칩과 대체 아이콘)만 진입점에 두고, 나머지 고른
// 200개는 청크 하나(lucideSet.ts)로 묶는다.
// Stands in for lucide-react/dynamicIconImports.mjs (an alias in vite.config.ts). The original imports each of its
// 1,912 icons dynamically, one chunk per icon. Here the three hot ones (globe, circle, circle-dot: source chips and
// fallbacks) stay in the entry, and the other 200 picked icons share one chunk (lucideSet.ts).
import type { ComponentType } from "react";
import { Circle, CircleDot, Globe } from "lucide-react";

type IconModule = { default: ComponentType<object> | undefined };
type IconImport = () => Promise<IconModule>;

/** lucideSet.ts 의 ICONS 와 같은 이름들(테스트가 둘을 맞춰 본다) / The same names as lucideSet.ts's ICONS (a test compares them). */
export const LAZY_ICON_NAMES = [
  "accessibility", "user", "cat", "arrow-right", "box", "building", "chart-line", "message-square", "wifi",
  "mouse-pointer", "palette", "code", "smartphone", "smile", "file", "dollar-sign", "cooking-pot", "gamepad",
  "house", "layout", "mail", "calculator", "heart-pulse", "music", "tree-pine", "map-pin", "bell", "users",
  "camera", "microscope", "sun", "shield", "shopping-cart", "share-2", "trophy", "leaf", "type", "clock",
  "wrench", "car", "plane", "cloud", "check", "circle-check", "circle-check-big", "x", "circle-x", "info",
  "triangle-alert", "circle-alert", "circle-help", "octagon-alert", "ban", "star", "heart", "building-2",
  "briefcase", "calendar", "calendar-days", "calendar-check", "phone", "link", "external-link", "file-text",
  "file-spreadsheet", "folder", "folder-open", "search", "settings", "lock", "lock-open", "shield-check",
  "shield-alert", "key", "chart-bar", "chart-pie", "chart-column", "chart-area", "trending-up", "trending-down",
  "circle-dollar-sign", "credit-card", "wallet", "receipt", "package", "truck", "train-front", "book",
  "book-open", "graduation-cap", "lightbulb", "rocket", "target", "flag", "award", "medal", "crown", "gift",
  "tag", "bookmark", "message-circle", "send", "download", "upload", "copy", "pencil", "trash-2", "plus",
  "minus", "arrow-left", "arrow-up", "arrow-down", "arrow-up-right", "chevron-right", "refresh-cw", "zap",
  "moon", "cloud-rain", "thermometer", "droplet", "wind", "coffee", "utensils", "video", "mic", "database",
  "server", "cpu", "terminal", "monitor", "laptop", "printer", "list", "list-checks", "clipboard",
  "clipboard-check", "clipboard-list", "percent", "hash", "layers", "layout-grid", "funnel",
  "sliders-horizontal", "hammer", "flask-conical", "stethoscope", "activity", "sparkles", "square", "triangle",
  "hourglass", "timer", "history", "scale", "landmark", "factory", "handshake", "thumbs-up", "thumbs-down",
  "eye", "eye-off", "badge-check", "megaphone", "headphones", "umbrella", "mountain", "waves", "tent",
  "shopping-bag", "store", "presentation", "inbox", "archive", "network", "workflow", "git-branch", "puzzle",
  "compass", "map", "navigation", "gauge", "alarm-clock", "user-check", "user-plus", "user-minus", "user-round",
  "id-card", "contact", "school", "hospital", "banknote", "piggy-bank", "coins", "file-check", "file-search",
  "notebook-pen", "pen-line", "message-square-text", "mails", "at-sign",
];

const ready = (icon: ComponentType<object>): IconImport => () => Promise.resolve({ default: icon });

const lazy = (name: string): IconImport => () =>
  import("./lucideSet").then((set) => ({ default: set.ICONS[name] }));

const icons: Record<string, IconImport> = {
  globe: ready(Globe as ComponentType<object>),
  circle: ready(Circle as ComponentType<object>),
  "circle-dot": ready(CircleDot as ComponentType<object>),
};

for (const name of LAZY_ICON_NAMES) icons[name] = lazy(name);

export default icons;
