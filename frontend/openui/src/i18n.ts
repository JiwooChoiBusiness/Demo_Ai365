// 섬 화면 글자의 한국어 · 영어. OpenUI(react-ui)는 글자를 바꾸는 API 가 없어 빌드 때 고친 자리(build/vendorPatches.ts)가
// 여기 사전을 읽는다. 기본은 한국어, opts.lang === "en" 이면 영어.
// Korean and English for the island's on-screen labels. OpenUI (react-ui) has no API to change its labels, so the
// places patched at build time (build/vendorPatches.ts) read this dictionary. Korean by default, English when
// opts.lang === "en".
import { createContext } from "react";

export type Lang = "ko" | "en";

/** 섬 하나의 언어(렌더 때 opts.lang) / One island's language (opts.lang at render time). */
export const LangContext = createContext<Lang>("ko");

export function toLang(value: unknown): Lang {
  return value === "en" ? "en" : "ko";
}

// 문자열 속성(placeholder · aria-label)은 컨텍스트를 읽을 수 없어, 마지막 render() 의 언어를 쓴다(데모는 화면 전체가 한 언어).
// String props (placeholder, aria-label) cannot read the context, so they use the last render()'s language (the
// demo shows one language across the page).
let current: Lang = "ko";

export function setCurrentLang(lang: Lang) {
  current = lang;
}

export function currentLang(): Lang {
  return current;
}

const KO: Record<string, string> = {
  Sources: "출처",
  "Related Queries": "관련 질문",
  "No data available": "표시할 데이터가 없습니다",
  "Show more": "더 보기",
  "Show less": "접기",
  "Select a month": "월 선택",
  "Select a date": "날짜 선택",
  "Select a range": "기간 선택",
  "Copy code": "코드 복사",
  "Copied to clipboard": "복사했습니다",
  // 본문 인용 번호 칩의 화면 읽기 이름 "출처 n: 제목" / the inline number chip's accessible name "Source n: title"
  Source: "출처",
  "Internal document": "사내 문서",
  "Local document": "로컬 문서",
  "Data analysis": "데이터 분석",
  Groupware: "그룹웨어",
  // 섬 자체 글자 / the island's own labels
  "Form answers:": "입력한 내용:",
  "Drawing the diagram when the answer is complete…": "답변이 끝나면 다이어그램을 그립니다…",
  "This diagram could not be drawn, so its code is shown instead.": "다이어그램을 그리지 못해 코드를 그대로 보여 줍니다.",
  "This answer could not be shown as a card, so its text is shown instead.": "답변을 카드로 표시하지 못해 글로 보여 줍니다.",
};

/** 화면 글자 하나 / One on-screen label. */
export function label(lang: Lang, key: string): string {
  return lang === "en" ? key : (KO[key] ?? key);
}

// 입력 검증 문구(@openuidev/lang-core builtInValidators) / form validation messages (lang-core's builtInValidators)
const KO_MESSAGES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^This field is required$/, () => "필수 항목입니다"],
  [/^At least one option is required$/, () => "하나 이상 선택해 주세요"],
  [/^Please enter a valid email$/, () => "올바른 이메일 주소를 입력해 주세요"],
  [/^Please enter a valid URL$/, () => "올바른 URL 을 입력해 주세요"],
  [/^Must be a number$/, () => "숫자를 입력해 주세요"],
  [/^Must be at least (\S+) characters$/, (m) => `${m[1]}자 이상 입력해 주세요`],
  [/^Must be no more than (\S+) characters$/, (m) => `${m[1]}자 이하로 입력해 주세요`],
  [/^Must be at least (\S+)$/, (m) => `${m[1]} 이상이어야 합니다`],
  [/^Must be no more than (\S+)$/, (m) => `${m[1]} 이하여야 합니다`],
  [/^Invalid format$/, () => "형식이 맞지 않습니다"],
  [/^Invalid number$/, () => "숫자가 아닙니다"],
];

/** 입력 검증 문구 하나 / One validation message. */
export function message(lang: Lang, text: string): string {
  if (lang === "en") return text;

  for (const [pattern, make] of KO_MESSAGES) {
    const match = text.match(pattern);

    if (match) return make(match);
  }

  return text;
}
