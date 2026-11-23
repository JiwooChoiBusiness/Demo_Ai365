// 폼에 입력한 값을 모델이 읽을 글로(예제 formAnswers.ts 와 같은 모양).
// 폼의 제출 단추는 단추 글만 담은 continue_conversation 동작을 낸다("Plan my trip based on my form submission").
// 값은 event.formState 에 { 폼이름: { 필드이름: { value } } } 모양으로 따로 오고, 메시지에 붙이지 않으면 사라진다.
// What the user filled in a form, as text the model can read (the same shape as the example's formAnswers.ts).
// A form's submit button fires a continue_conversation action whose message is only the button's text. The values
// come separately in event.formState, shaped { formName: { fieldName: { value } } }, and are lost unless they are
// sent with the message.
import { label, type Lang } from "./i18n";

type Field = { value?: unknown };

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}T00:00:00(\.000)?Z$/;

function formatDate(date: Date): string {
  if (Number.isNaN(date.getTime())) return "";

  return date.toLocaleDateString("en-CA"); // 2026-10-01, 현지 시각 / in local time
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";

  if (value instanceof Date) return formatDate(value);

  if (typeof value === "string") {
    return DATE_ONLY.test(value) ? formatDate(new Date(value)) : value.trim();
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value.map(formatValue).filter(Boolean).join(", ");
  }

  if (typeof value === "object") {
    // 날짜 범위 { from, to } / a DatePicker range
    const { from, to } = value as { from?: unknown; to?: unknown };

    if ("from" in value || "to" in value) {
      const start = formatValue(from);
      const end = formatValue(to);

      return start && end ? `${start} to ${end}` : start || end;
    }

    return JSON.stringify(value);
  }

  return String(value);
}

function isField(value: unknown): value is Field {
  return typeof value === "object" && value !== null && "value" in value;
}

/** 채운 필드를 "- 이름: 값" 줄로, 빈 필드는 뺀다 / The filled fields as "- name: value" lines, empty ones left out. */
export function formAnswerLines(formState?: Record<string, unknown>): string[] {
  if (!formState) return [];

  const lines: string[] = [];

  const addFields = (fields: Record<string, unknown>) => {
    for (const [name, field] of Object.entries(fields)) {
      const text = formatValue(isField(field) ? field.value : undefined);

      if (text) lines.push(`- ${name}: ${text}`);
    }
  };

  for (const [key, entry] of Object.entries(formState)) {
    if (isField(entry)) {
      addFields({ [key]: entry });
    } else if (typeof entry === "object" && entry !== null) {
      addFields(entry as Record<string, unknown>);
    }
  }

  return lines;
}

/** 보낼 글: 단추 글 다음에 폼 값 / The message to send: the button's text, then the form's answers. */
export function withFormAnswers(message: string, formState?: Record<string, unknown>, lang: Lang = "ko"): string {
  const lines = formAnswerLines(formState);

  if (lines.length === 0) return message;

  return `${message}\n\n${label(lang, "Form answers:")}\n${lines.join("\n")}`;
}
