// 모델이 프로그램 안에서 @이름(...) 으로 부르는 함수(예제 functions.ts 그대로). 카드가 입력을 모델에 보내지 않고
// 화면에서 바로 계산하게 한다: 계산기 단추, 견적 입력, 단위 변환.
// Functions the model calls as @Name(...) inside a program (the example's functions.ts as is), so a card can compute
// in the page instead of sending its inputs to the assistant: a calculator's keys, an estimator's inputs, a converter.
//
// OpenUI 의 내장 함수(@Sum, @Round, @Max…)는 숫자 · 목록을 다룬다. 여기 함수는 화면 도구가 더 필요한 것을 채운다:
// 입력칸은 글자를 담고, 키패드는 식을 만들고, 결과는 형식을 갖춰 보여야 한다. 모두 순수 함수이고, 던지거나 returns 에
// 맞지 않는 결과는 런타임이 null 로 바꾼다.
// OpenUI's built-ins (@Sum, @Round, @Max…) work on numbers and lists. These fill what a working tool also needs:
// text inputs hold strings, a keypad builds an expression, a result needs formatting. Each is pure. The runtime
// turns a throw or a result that does not match `returns` into null.
import { z } from "zod/v4";
import { defineFunction } from "@openuidev/react-lang";

const numberOrText = z.union([z.number(), z.string()]);

// ============================================================
// 계산 / Arithmetic
// ============================================================

// 키패드 기호를 파서 기호로 / The keypad's symbols, as the parser reads them.
const SYMBOLS: Record<string, string> = { "×": "*", "÷": "/", "−": "-", x: "*" };

type Token = number | string;

function tokenize(expression: string): Token[] {
  const tokens: Token[] = [];
  const text = expression.replace(/[×÷−x]/g, (symbol) => SYMBOLS[symbol]);
  let index = 0;

  while (index < text.length) {
    const char = text[index];

    if (char === " " || char === ",") {
      index++;
    } else if (/[0-9.]/.test(char)) {
      const match = /^\d*\.?\d*(?:e[+-]?\d+)?/i.exec(text.slice(index))![0];
      const value = Number(match);

      if (!match || match === "." || Number.isNaN(value)) {
        throw new Error(`bad number at ${index}`);
      }

      tokens.push(value);
      index += match.length;
    } else if ("+-*/%()".includes(char)) {
      tokens.push(char);
      index++;
    } else {
      throw new Error(`unexpected "${char}"`);
    }
  }

  return tokens;
}

// expression := term (("+" | "-") term)*
// term       := factor (("*" | "/" | "%") factor)*
// factor     := ("+" | "-") factor | number | "(" expression ")"
function evaluate(tokens: Token[]): number {
  let position = 0;

  const peek = () => tokens[position];
  const next = () => tokens[position++];

  function factor(): number {
    const token = next();

    if (token === "-") return -factor();
    if (token === "+") return factor();
    if (typeof token === "number") return token;

    if (token === "(") {
      const value = expression();

      if (next() !== ")") throw new Error("missing )");
      return value;
    }

    throw new Error("expected a number");
  }

  function term(): number {
    let value = factor();

    while (peek() === "*" || peek() === "/" || peek() === "%") {
      const operator = next();
      const right = factor();

      if (operator === "*") value *= right;
      else if (operator === "/") value /= right;
      else value %= right;
    }

    return value;
  }

  function expression(): number {
    let value = term();

    while (peek() === "+" || peek() === "-") {
      value = next() === "+" ? value + term() : value - term();
    }

    return value;
  }

  const value = expression();

  if (position !== tokens.length) throw new Error("unexpected token");

  return value;
}

// "12+6×2" 의 값, 계산식이 아니면 null. 0.1 + 0.2 는 0.30000000000000004 가 아니라 0.3.
// The value of "12+6×2", or null for anything that is not arithmetic. 0.1 + 0.2 is 0.3, not 0.30000000000000004.
export function calculate(expression: unknown): number | null {
  if (typeof expression === "number") {
    return Number.isFinite(expression) ? expression : null;
  }

  if (typeof expression !== "string" || !expression.trim()) return null;

  try {
    const value = evaluate(tokenize(expression));

    return Number.isFinite(value) ? Number(value.toPrecision(12)) : null;
  } catch {
    return null;
  }
}

export const Calc = defineFunction({
  name: "Calc",
  description:
    'Works out arithmetic text: + - * / %, parentheses, and the keypad\'s × ÷ −. @Calc("12+6×2") is 24. Gives fallback for text that is not arithmetic (e.g. "Error").',
  params: z.object({
    expression: numberOrText,
    fallback: numberOrText.optional(),
  }),
  returns: numberOrText,
  fn: ({ expression, fallback }) => {
    const value = calculate(expression);

    if (value !== null) return value;
    if (fallback !== undefined) return fallback;

    throw new Error("not arithmetic");
  },
});

// ============================================================
// 숫자 / Numbers
// ============================================================

// 입력칸 글자에서 숫자: "1,200" 과 " 30 " 도 숫자로 / A number from an input's text: "1,200" and " 30 " too.
export function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return toNumber(value[0]);
  if (typeof value !== "string") return null;

  const text = value.replace(/[,\s]/g, "");

  if (!text) return null;

  const number = Number(text);

  return Number.isFinite(number) ? number : null;
}

export const ToNumber = defineFunction({
  name: "ToNumber",
  description:
    "A number from an input's text, e.g. \"1,200\" → 1200; a Slider's [30] → 30. Empty or not a number gives fallback (0 by default).",
  params: z.object({
    value: z.any(),
    fallback: z.number().optional(),
  }),
  returns: z.number(),
  fn: ({ value, fallback }) => toNumber(value) ?? fallback ?? 0,
});

export const Clamp = defineFunction({
  name: "Clamp",
  description:
    "value kept between min and max, e.g. no negatives or at most 100: @Clamp(@ToNumber($rate), 0, 100).",
  params: z.object({
    value: z.number(),
    min: z.number(),
    max: z.number(),
  }),
  returns: z.number(),
  fn: ({ value, min, max }) => Math.min(Math.max(value, min), max),
});

export const FormatNumber = defineFunction({
  name: "FormatNumber",
  description:
    "A number for display with thousands separators: @FormatNumber(6000000) is \"6,000,000\"; decimals fixes the decimal places (up to 2 by default).",
  params: z.object({
    value: z.number(),
    decimals: z.number().optional(),
  }),
  returns: z.string(),
  fn: ({ value, decimals }) => {
    if (!Number.isFinite(value)) throw new Error("not a number");

    const digits = decimals === undefined ? undefined : Math.min(Math.max(decimals, 0), 10);

    return value.toLocaleString("en-US", {
      minimumFractionDigits: digits ?? 0,
      maximumFractionDigits: digits ?? 2,
    });
  },
});

// ============================================================
// 글자 / Text
// ============================================================

export const Substring = defineFunction({
  name: "Substring",
  description:
    "Part of a text, from start up to end (not included); a negative end counts from the end. Backspace: @Substring($display, 0, -1).",
  params: z.object({
    text: numberOrText,
    start: z.number(),
    end: z.number().optional(),
  }),
  returns: z.string(),
  fn: ({ text, start, end }) => String(text).slice(start, end),
});

export const Length = defineFunction({
  name: "Length",
  description: "The number of characters in a text.",
  params: z.object({ text: numberOrText }),
  returns: z.number(),
  fn: ({ text }) => String(text).length,
});

export const functions = [Calc, ToNumber, Clamp, FormatNumber, Substring, Length];
