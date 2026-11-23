// 빌드 출력 보조 플러그인 / Build output helper plugins.
// - 청크 최소화 / chunk minification
// - version.txt: 빌드 입력의 내용 해시(build/inputVersion.mjs). adapter 의 AI365_OUI_VER 와 함께 올린다.
//   version.txt: a content hash of the build inputs (build/inputVersion.mjs), bumped together with the adapter's
//   AI365_OUI_VER.
import fs from "node:fs";
import path from "node:path";
import { transformWithEsbuild, type Plugin } from "vite";

/**
 * 라이브러리 모드의 ES 출력은 Vite 가 공백을 줄이지 않는다(다시 묶일 라이브러리용). 섬은 브라우저가 바로 읽는 최종
 * 번들이라, 모든 renderChunk 가 끝난 뒤(generateBundle) 청크마다 esbuild 로 다시 줄인다(라이선스 주석은 끝에 남긴다).
 * Vite leaves whitespace in library-mode ES output (meant to be bundled again). The island is a final bundle the
 * browser reads directly, so once every renderChunk has run (generateBundle) each chunk is minified again with
 * esbuild (license comments kept at the end).
 */
export function minifyChunks(): Plugin {
  return {
    name: "ai365-oui-minify",
    apply: "build",
    enforce: "post",
    async generateBundle(_options, bundle) {
      for (const file of Object.values(bundle)) {
        if (file.type !== "chunk") continue;

        const result = await transformWithEsbuild(file.code, file.fileName, {
          minify: true,
          format: "esm",
          target: "es2020",
          legalComments: "eof",
        });

        file.code = result.code;
      }
    },
  };
}

/**
 * 진입점(openui.js)은 다시 내보내기만 하고, 어떤 청크도 진입점 파일을 가져오지 않는다. 화면은 openui.js?v=<버전> 으로
 * 부르는데, 청크가 쿼리 없는 openui.js 를 가져오면 브라우저는 다른 모듈로 보고 번들 전체를 한 번 더 평가한다
 * (window.AI365_OpenUI 두 벌 · React 두 벌). 어기면 빌드를 멈춘다.
 * The entry (openui.js) only re-exports, and no chunk imports the entry file. The page loads openui.js?v=<version>;
 * a chunk importing plain openui.js would be a different module to the browser, so the whole bundle would run again
 * (two window.AI365_OpenUI, two Reacts). The build stops if either rule is broken.
 */
export function thinEntry(entryFile: string, mainModule: string): Plugin {
  return {
    name: "ai365-oui-thin-entry",
    apply: "build",
    enforce: "post",
    generateBundle(_options, bundle) {
      const files = Object.values(bundle);
      const entry = files.find((file) => file.type === "chunk" && file.isEntry);

      if (!entry || entry.type !== "chunk" || entry.fileName !== entryFile) this.error(`entry ${entryFile} missing`);

      const own = Object.entries(entry.modules).filter(([, info]) => info.renderedLength > 0);

      if (own.length > 0) this.error(`entry ${entryFile} holds code: ${own.map(([id]) => id).join(", ")}`);

      const core = files.find(
        (file) => file.type === "chunk" && Object.keys(file.modules).some((id) => id.replace(/\\/g, "/").endsWith(mainModule)),
      );

      if (!core || core.type !== "chunk" || !entry.imports.includes(core.fileName)) {
        this.error(`entry ${entryFile} must re-export the chunk holding ${mainModule}`);
      }

      for (const file of files) {
        if (file.type === "chunk" && (file.imports.includes(entryFile) || file.dynamicImports.includes(entryFile))) {
          this.error(`chunk ${file.fileName} imports the entry ${entryFile}`);
        }
      }
    },
  };
}

/** 빌드가 끝나면 version.txt 를 쓴다 / Writes version.txt once the bundle is written. */
export function versionFile(version: string): Plugin {
  return {
    name: "ai365-oui-version",
    apply: "build",
    writeBundle(options) {
      if (!options.dir) return;

      fs.writeFileSync(path.join(options.dir, "version.txt"), `${version}\n`);
    },
  };
}
