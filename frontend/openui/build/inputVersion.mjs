// 섬 번들 버전 = 빌드 입력(src · build · 설정 · lock)의 내용 해시 앞 10자리. vite.config.ts(번들 → version.txt)와
// scripts/gen-prompt.mjs(라이브러리 스키마 → dist-node/library.schema.json)가 함께 쓰므로, 둘이 같은 입력에서
// 만들어졌는지 테스트가 맞춰 볼 수 있다.
// The island bundle version = the first 10 hex digits of a content hash of the build inputs (src, build, the
// configs, the lock). vite.config.ts (the bundle → version.txt) and scripts/gen-prompt.mjs (the library schema →
// dist-node/library.schema.json) both use it, so a test can check the two came from the same inputs.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

function walk(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);

    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
}

/** 입력 파일 내용으로 만든 버전 문자열 / A version string made from the input files' contents. */
export function inputVersion(root) {
  const files = [];

  for (const dir of ["src", "build"]) walk(path.join(root, dir), files);

  for (const name of ["vite.config.ts", "package.json", "package-lock.json", "tsconfig.json"]) {
    files.push(path.join(root, name));
  }

  const hash = createHash("sha256");

  for (const file of files.map((f) => path.relative(root, f).replace(/\\/g, "/")).sort()) {
    // 줄 끝을 맞춰 운영체제와 무관하게 / normalise line endings so the OS does not matter
    const text = fs.readFileSync(path.join(root, file), "utf8").replace(/\r\n/g, "\n");

    hash.update(`${file}\n${text}\n`);
  }

  return hash.digest("hex").slice(0, 10);
}
