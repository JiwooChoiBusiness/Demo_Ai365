// `npm run gen:prompt`: src/library.ts 의 라이브러리 · 프롬프트 옵션으로 시스템 프롬프트를 만든다.
// 1. OpenUI CLI(`openui generate`, 원격 측정 끔)를 임시 폴더로 돌린다(CLI 는 .spec.json 을 옆에 함께 쓴다).
// 2. 프롬프트의 em dash 를 "-" 로 바꿔(모델이 답에 줄표를 따라 쓰지 않게) app/prompts/openui_system_prompt.txt 에 쓴다.
// 3. 검증 도구(scripts/validate.mjs)가 쓸 라이브러리 JSON 스키마를 dist-node/library.schema.json 에 쓴다.
// 4. 글자 수와 절별 크기를 출력한다.
// `npm run gen:prompt`: builds the system prompt from src/library.ts's library and prompt options.
// 1. Runs the OpenUI CLI (`openui generate`, telemetry off) into a temp folder (the CLI writes a .spec.json next to it).
// 2. Turns the prompt's em dashes into "-" (so the model does not copy them into answers) and writes it to
//    app/prompts/openui_system_prompt.txt.
// 3. Writes the library's JSON schema for the validator (scripts/validate.mjs) to dist-node/library.schema.json.
// 4. Prints the character count and the size of each section.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { inputVersion } from "../build/inputVersion.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PROMPT_OUT = path.resolve(ROOT, "../../app/prompts/openui_system_prompt.txt");
const SCHEMA_OUT = path.resolve(ROOT, "dist-node/library.schema.json");
const CLI = path.join(ROOT, "node_modules/@openuidev/cli/dist/index.js");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ai365-oui-prompt-"));

try {
  execFileSync(
    process.execPath,
    [CLI, "--no-telemetry", "generate", "./src/library.ts", "--out", path.join(tmp, "prompt.txt"), "--no-interactive"],
    {
      cwd: ROOT,
      stdio: ["ignore", "ignore", "inherit"],
      env: { ...process.env, DO_NOT_TRACK: "1", OPENUI_TELEMETRY_DISABLED: "1" },
    },
  );

  const raw = fs.readFileSync(path.join(tmp, "prompt.txt"), "utf8").replace(/\r\n/g, "\n");
  const prompt = `${raw.replace(new RegExp(String.fromCharCode(0x2014), "g"), "-").trimEnd()}\n`;
  const spec = JSON.parse(fs.readFileSync(path.join(tmp, "prompt.spec.json"), "utf8"));

  fs.mkdirSync(path.dirname(PROMPT_OUT), { recursive: true });
  fs.writeFileSync(PROMPT_OUT, prompt);

  // version = 같은 입력으로 만든 번들의 version.txt 와 같은 값(테스트가 맞춰 본다)
  // version = the same value as version.txt of a bundle built from the same inputs (a test compares them)
  fs.mkdirSync(path.dirname(SCHEMA_OUT), { recursive: true });
  fs.writeFileSync(
    SCHEMA_OUT,
    `${JSON.stringify(
      {
        version: inputVersion(ROOT),
        root: spec.root ?? "Card",
        components: Object.keys(spec.components ?? {}).sort(),
        schema: spec.schema,
      },
      null,
      1,
    )}\n`,
  );

  // 절별 크기 / section sizes
  const sections = [];
  let name = "(preamble)";
  let size = 0;

  for (const line of prompt.split("\n")) {
    if (line.startsWith("## ")) {
      sections.push([name, size]);
      name = line.slice(3);
      size = 0;
    }

    size += line.length + 1;
  }

  sections.push([name, size]);

  console.log(`prompt: ${path.relative(path.resolve(ROOT, "../.."), PROMPT_OUT)} ${prompt.length} chars`);

  for (const [section, chars] of sections) console.log(`  ${String(chars).padStart(6)}  ${section}`);

  console.log(`schema: ${path.relative(ROOT, SCHEMA_OUT)} (${spec.schema ? Object.keys(spec.schema.$defs ?? {}).length : 0} defs)`);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
