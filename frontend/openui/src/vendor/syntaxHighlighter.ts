// react-syntax-highlighter 대신(vite.config.ts 의 별칭). OpenUI 의 CodeBlock 은 Prism 전체판(refractor 언어 300개,
// 번들의 약 1MB)을 가져온다. 여기서는 가벼운 판(PrismLight)에 자주 쓰는 언어만 등록한다. 등록하지 않은 언어는 강조 없이
// 글자로 보인다.
// Stands in for react-syntax-highlighter (an alias in vite.config.ts). OpenUI's CodeBlock imports the full Prism
// build (300 refractor languages, about 1MB of the bundle). Here the light build (PrismLight) gets the common
// languages only; any other language shows as plain, unhighlighted text.
import PrismLight from "react-syntax-highlighter/dist/esm/prism-light.js";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash.js";
import c from "react-syntax-highlighter/dist/esm/languages/prism/c.js";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp.js";
import csharp from "react-syntax-highlighter/dist/esm/languages/prism/csharp.js";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css.js";
import diff from "react-syntax-highlighter/dist/esm/languages/prism/diff.js";
import docker from "react-syntax-highlighter/dist/esm/languages/prism/docker.js";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go.js";
import ini from "react-syntax-highlighter/dist/esm/languages/prism/ini.js";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java.js";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript.js";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json.js";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx.js";
import kotlin from "react-syntax-highlighter/dist/esm/languages/prism/kotlin.js";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown.js";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup.js";
import php from "react-syntax-highlighter/dist/esm/languages/prism/php.js";
import powershell from "react-syntax-highlighter/dist/esm/languages/prism/powershell.js";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python.js";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust.js";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql.js";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx.js";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript.js";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml.js";

const LANGUAGES: [string, unknown][] = [
  ["bash", bash],
  ["c", c],
  ["cpp", cpp],
  ["csharp", csharp],
  ["css", css],
  ["diff", diff],
  ["docker", docker],
  ["go", go],
  ["ini", ini],
  ["java", java],
  ["javascript", javascript],
  ["json", json],
  ["jsx", jsx],
  ["kotlin", kotlin],
  ["markdown", markdown],
  ["markup", markup],
  ["php", php],
  ["powershell", powershell],
  ["python", python],
  ["rust", rust],
  ["sql", sql],
  ["tsx", tsx],
  ["typescript", typescript],
  ["yaml", yaml],
];

// 언어 정의가 별칭(js · ts · py · sh · html · yml · md · cs 등)도 함께 등록한다
// The language definitions register their aliases too (js, ts, py, sh, html, yml, md, cs, ...)
for (const [name, language] of LANGUAGES) {
  (PrismLight as unknown as { registerLanguage(name: string, language: unknown): void }).registerLanguage(name, language);
}

export const Prism = PrismLight;

export default PrismLight;
