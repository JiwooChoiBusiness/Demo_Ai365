// 화면에서 바로 도는 도구용 컴포넌트(예제 Tools.tsx 그대로): 계산기 · 견적 · 변환기. 상태는 $변수에 있고 단추는 @Set 으로,
// 입력칸은 입력할 때마다 바꾼다. 모델에는 아무것도 가지 않는다.
// Components for tools that work in the page (the example's Tools.tsx as is): a calculator, an estimator, a
// converter. Their state lives in $variables, which buttons change with @Set and inputs change as the user types;
// nothing goes to the assistant.
//
// - Readout: 오른쪽 정렬 큰 값 + 작은 설명 / a display, a large right-aligned value with a small caption
// - ButtonGrid: 같은 폭 칸에 단추들(키패드) / buttons in equal columns, each filling its cell: a keypad
// - ToolField: Form 밖 라벨 붙은 입력칸(OpenUI FormControl 은 Form 안에서만 동작) / a labelled input outside a Form
import type { ReactNode } from "react";
import { z } from "zod/v4";
import { defineComponent } from "@openuidev/react-lang";

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

export const Readout = defineComponent({
  name: "Readout",
  props: z.object({
    value: z.any(),
    caption: z.string().optional(),
  }),
  description:
    'A tool\'s display: a large right-aligned value with a small caption above it, e.g. Readout($display, "Calculator").',
  component: ({ props }) => (
    <div className="readout" role="status" aria-live="polite">
      {text(props.caption) && <div className="readout-caption">{text(props.caption)}</div>}
      <div className="readout-value">{text(props.value) || "0"}</div>
    </div>
  ),
});

export const ButtonGrid = defineComponent({
  name: "ButtonGrid",
  props: z.object({
    buttons: z.array(z.any()),
    columns: z.number().optional(),
  }),
  description:
    "Buttons in equal columns (4 by default), each filling its cell: a keypad. Every Button in it has an action, usually @Set.",
  component: ({ props, renderNode }) => {
    const columns = Math.min(Math.max(Math.round(Number(props.columns) || 4), 1), 8);

    return (
      <div className="button-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
        {renderNode(props.buttons as never) as ReactNode}
      </div>
    );
  },
});

export const ToolField = defineComponent({
  name: "ToolField",
  props: z.object({
    label: z.string(),
    input: z.any(),
    hint: z.string().optional(),
  }),
  description:
    'A labelled input of a live tool, outside any Form: an Input, Slider or Select bound to a $variable, e.g. ToolField("Employees", Input("employees", "100", "number", null, $employees)).',
  component: ({ props, renderNode }) => (
    <div className="tool-field">
      <div className="tool-field-label">{text(props.label)}</div>
      {renderNode(props.input as never) as ReactNode}
      {text(props.hint) && <div className="tool-field-hint">{text(props.hint)}</div>}
    </div>
  ),
});
