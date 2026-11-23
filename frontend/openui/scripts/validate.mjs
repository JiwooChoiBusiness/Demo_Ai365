// OpenUI 프로그램 검증 도구(테스트 · Gemini 준수율 측정용). 섬과 같은 파서(@openuidev/lang-core 의
// createParser + enrichErrors)에 이 라이브러리의 컴포넌트 집합(dist-node/library.schema.json, `npm run gen:prompt` 가
// 만든다)을 넣어 파싱한다.
// The OpenUI program checker (for tests and for scoring Gemini's outputs). It parses with the same parser as the
// island (@openuidev/lang-core's createParser + enrichErrors) and this library's component set
// (dist-node/library.schema.json, written by `npm run gen:prompt`).
//
// 쓰는 법 / Usage:
//   node scripts/validate.mjs program.txt            파일 하나 → JSON 한 줄 / one file → one JSON line
//   node scripts/validate.mjs < program.txt          stdin 도 같다 / stdin works the same
//   node scripts/validate.mjs --batch answers.jsonl  줄마다 {"id","program"} → 줄마다 결과 / one result per line
//
// 결과 / Result: {ok, hasRoot, statements, errors: [...], unknownComponents: [...], unresolved: [...]}
//   ok = 루트가 있고 경고가 아닌 오류가 없다 / there is a root and no error other than warnings
// 종료 코드 / Exit code: 하나 검사는 ok 면 0, 아니면 1 · 묶음은 늘 0 · 쓰는 법이 틀리면 2
//   single: 0 when ok, else 1; batch: always 0; usage error: 2
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// 원격 측정은 기본으로 꺼져 있지만 확실히 / runtime telemetry is opt-in already; make sure
process.env.OPENUI_TELEMETRY_DISABLED = "1";
process.env.DO_NOT_TRACK = "1";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCHEMA_FILE = path.join(ROOT, "dist-node/library.schema.json");

const { createParser, enrichErrors } = await import("@openuidev/lang-core");

if (!fs.existsSync(SCHEMA_FILE)) {
  process.stderr.write(`missing ${SCHEMA_FILE}: run "npm run gen:prompt" in frontend/openui first\n`);
  process.exit(2);
}

const library = JSON.parse(fs.readFileSync(SCHEMA_FILE, "utf8"));
const parser = createParser(library.schema, library.root);
const componentNames = library.components;

// 섬의 toProgram 과 같다: ``` 펜스 줄을 지운다 / same as the island's toProgram: drops ``` fence lines
const FENCE_LINE = /^\s*```[\w-]*\s*$/;

function toProgram(text) {
  return String(text ?? "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => !FENCE_LINE.test(line))
    .join("\n")
    .trim();
}

/** 프로그램 하나 검사 / Checks one program. */
function validate(text) {
  const program = toProgram(text);
  let result;

  try {
    result = parser.parse(program);
  } catch (error) {
    return {
      ok: false,
      hasRoot: false,
      statements: 0,
      errors: [{ source: "parser", code: "parse-exception", message: `Parser crashed: ${error?.message ?? error}` }],
      unknownComponents: [],
      unresolved: [],
    };
  }

  const errors = enrichErrors(result.meta.errors, library.schema, componentNames);

  // Renderer 와 같이: 문장이 하나도 없으면 parse-failed / like the Renderer: no statement at all is parse-failed
  if (program && !result.meta.statementCount) {
    errors.unshift({
      source: "parser",
      code: "parse-failed",
      message: "Response could not be parsed as valid openui-lang",
      hint: `The entire response must be valid openui-lang code starting with root = ${library.root}(...)`,
    });
  }

  const unknownComponents = [
    ...new Set(errors.filter((e) => e.code === "unknown-component").map((e) => e.component).filter(Boolean)),
  ];
  const hasRoot = result.root !== null;

  return {
    ok: hasRoot && errors.every((e) => e.severity === "warning"),
    hasRoot,
    statements: result.meta.statementCount,
    errors,
    unknownComponents,
    unresolved: result.meta.unresolved,
  };
}

function readStdin() {
  return fs.readFileSync(0, "utf8");
}

const args = process.argv.slice(2);

if (args[0] === "--batch") {
  if (!args[1]) {
    process.stderr.write("usage: node scripts/validate.mjs --batch <file.jsonl>\n");
    process.exit(2);
  }

  const lines = fs.readFileSync(args[1], "utf8").split(/\r?\n/);
  const out = [];

  for (const line of lines) {
    if (!line.trim()) continue;

    let item;

    try {
      item = JSON.parse(line);
    } catch (error) {
      out.push(JSON.stringify({ id: null, ok: false, hasRoot: false, statements: 0, errors: [{ code: "bad-input", message: String(error?.message ?? error) }], unknownComponents: [], unresolved: [] }));
      continue;
    }

    out.push(JSON.stringify({ id: item?.id ?? null, ...validate(item?.program ?? "") }));
  }

  process.stdout.write(out.length ? `${out.join("\n")}\n` : "");
} else if (args.length > 1 || (args[0] && args[0].startsWith("--"))) {
  process.stderr.write("usage: node scripts/validate.mjs [program-file] | --batch <file.jsonl>\n");
  process.exit(2);
} else {
  const text = args[0] ? fs.readFileSync(args[0], "utf8") : readStdin();
  const result = validate(text);

  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.ok ? 0 : 1;
}
