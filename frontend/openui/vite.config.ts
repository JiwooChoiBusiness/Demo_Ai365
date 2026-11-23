// OpenUI 섬 번들 빌드(라이브러리 모드). 결과는 저장소의 static/openui/ 로 간다(배포 서버는 npm 을 돌리지 않는다).
// - static/openui/openui.js : ES 모듈 진입점(다시 내보내기만 하는 얇은 껍데기)
// - static/openui/chunks/main-<해시>.js: 섬 본체(React 포함, 호스트 화면에는 React 가 없다)
// - static/openui/chunks/   : 그 밖의 동적 청크(mermaid · 아이콘 묶음 등, 쓸 때만 내려받는다)
// - static/openui/openui.css: 섬 CSS(.ai365-oui · .ai365-oui-portal 안으로만)
// - static/openui/version.txt: 입력 내용 해시
// The OpenUI island bundle build (library mode). The output goes to the repo's static/openui/ (the deploy server
// does not run npm):
// - static/openui/openui.js : the ES module entry (a thin shell that only re-exports)
// - static/openui/chunks/main-<hash>.js: the island core (React included; the host page has no React)
// - static/openui/chunks/   : the other dynamic chunks (mermaid, the icon set, ...), fetched only when used
// - static/openui/openui.css: the island CSS (inside .ai365-oui and .ai365-oui-portal only)
// - static/openui/version.txt: a hash of the inputs
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { cssScope } from "./build/cssScope";
import { HOOKS_ALIAS, nodeEnvBrackets, vendorPatches } from "./build/vendorPatches";
import { inputVersion } from "./build/inputVersion.mjs";
import { minifyChunks, thinEntry, versionFile } from "./build/output";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(ROOT, "../../static/openui");

// emptyOutDir 가 static/openui 밖을 지우는 일이 없게 / emptyOutDir must never clear anything but static/openui
if (path.basename(OUT_DIR) !== "openui" || path.basename(path.dirname(OUT_DIR)) !== "static") {
  throw new Error(`unexpected outDir: ${OUT_DIR}`);
}

const VERSION = inputVersion(ROOT);

export default defineConfig({
  root: ROOT,
  plugins: [react(), nodeEnvBrackets(), vendorPatches(), minifyChunks(), thinEntry("openui.js", "/src/api.tsx"), versionFile(VERSION)],
  define: {
    // 라이브러리 모드는 process.env 를 바꾸지 않는다: 운영 빌드로 고정(개발 도구 · 경고 제거)
    // Library mode leaves process.env alone: pin it to production (drops dev tools and warnings)
    "process.env.NODE_ENV": JSON.stringify("production"),
    __AI365_OUI_VERSION__: JSON.stringify(VERSION),
  },
  resolve: {
    alias: [
      { find: HOOKS_ALIAS, replacement: path.resolve(ROOT, "src/vendor/hooks.tsx") },
      // 아이콘: lucide 전체(1,900여 개 청크) 대신 고른 묶음 / icons: a picked set instead of all of lucide
      { find: /^lucide-react\/dynamicIconImports\.mjs$/, replacement: path.resolve(ROOT, "src/vendor/lucideIcons.ts") },
      // 수식(KaTeX)은 CSS 없이 깨져 보이므로 끈다 / math (KaTeX) renders broken without its CSS, so it is off
      { find: /^rehype-katex$/, replacement: path.resolve(ROOT, "src/vendor/rehypeKatexOff.ts") },
      // 코드 강조: Prism 전체판 대신 가벼운 판 + 자주 쓰는 언어 / code: the light Prism build with the common languages
      { find: /^react-syntax-highlighter$/, replacement: path.resolve(ROOT, "src/vendor/syntaxHighlighter.ts") },
      {
        find: /^react-syntax-highlighter\/dist\/cjs\/styles\/prism\/index\.js$/,
        replacement: path.resolve(ROOT, "src/vendor/syntaxStyles.ts"),
      },
    ],
    dedupe: ["react", "react-dom"],
  },
  css: {
    postcss: { plugins: [cssScope()] },
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    target: "es2020",
    minify: "esbuild",
    sourcemap: false,
    cssCodeSplit: false,
    reportCompressedSize: true,
    chunkSizeWarningLimit: 4096,
    lib: {
      entry: path.resolve(ROOT, "src/main.tsx"),
      formats: ["es"],
      fileName: () => "openui.js",
      cssFileName: "openui",
    },
    rollupOptions: {
      // 진입점은 자기 내보내기만(공유 코드를 담지 않는다). 지연 청크가 진입점 파일을 가져오면, 화면이
      // openui.js?v=<버전> 으로 부른 진입점과 주소가 달라 번들 전체가 두 번 평가된다(window.AI365_OpenUI 두 벌).
      // The entry exposes its own exports only (it holds no shared code). If lazy chunks imported the entry file,
      // its URL would differ from the page's openui.js?v=<version> and the whole bundle would run twice (two
      // window.AI365_OpenUI).
      // 그래서 Rollup 은 본체를 chunks/main-<해시>.js 로 떼어 내고 진입점은 다시 내보내기만 남긴다(build/output.ts 의
      // thinEntry 가 확인). manualChunks 는 쓰지 않는다: 의존을 나무 흔들기 전에 끌어와 지연 청크(KaTeX · 아이콘 묶음)까지
      // 본체에 섞는다.
      // So Rollup splits the core into chunks/main-<hash>.js and leaves the entry as re-exports only (checked by
      // thinEntry in build/output.ts). No manualChunks: it pulls dependencies in before tree-shaking and would merge
      // lazy chunks (KaTeX, the icon set) into the core.
      preserveEntrySignatures: "strict",
      output: {
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (asset) =>
          (asset.names ?? []).some((name) => name.endsWith(".css")) ? "openui.css" : "chunks/[name]-[hash][extname]",
      },
    },
  },
});
