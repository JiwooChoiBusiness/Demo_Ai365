// 대시보드 컴포넌트(예제 Dashboard.tsx 그대로). OpenUI 의 채팅 Card 는 자식을 위에서 아래로만 쌓아 대시보드를 못 짠다.
// Dashboard components (the example's Dashboard.tsx as is). OpenUI's chat Card only stacks children top to bottom.
//
// - Columns: 패널을 나란히(한 줄에 둘이나 셋, 좁으면 한 줄) / panels side by side, two or three to a row
// - Panel: Columns 한 칸(차트 · 표 · 글) / one titled box of a Columns row (a chart, a table, text)
// - StatStrip: 맨 위 큰 숫자들(라벨 · 변화 · 이모지 · 태그) / the big numbers across the top
// - FunnelChart: 깔때기 단계 막대와 다음 단계로 넘어간 비율 / a funnel's stages as bars with the share that went on
// - ProgressBar: 표 칸 안의 값과 막대 / a value with a bar, for a Table cell
//
// Panel · Stat · FunnelStage 는 속성만 담고 부모가 그린다(OpenUI ListBlock 이 ListItem 을 그리듯).
// Panel, Stat and FunnelStage only carry props; their parents draw them, the way OpenUI's ListBlock draws its ListItems.
import type { ReactNode } from "react";
import { z } from "zod/v4";
import { defineComponent } from "@openuidev/react-lang";

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function numberOf(value: unknown): number {
  const number = typeof value === "number" ? value : Number(value);

  return Number.isFinite(number) ? number : 0;
}

// ============================================================
// 칸과 패널 / Columns and panels
// ============================================================

export const Panel = defineComponent({
  name: "Panel",
  props: z.object({
    title: z.string(),
    content: z
      .array(z.any())
      .describe("Blocks inside the panel: a chart, a Table, FunnelChart, TextContent, Tag or Callout"),
    subtitle: z.string().optional(),
    wide: z.boolean().optional().describe("true: twice as wide as the other panels of its row"),
  }),
  description:
    "One titled box of a Columns row. content is a list of blocks: a chart, Table, FunnelChart, TextContent or Callout. wide true makes it twice as wide as the others in its row.",
  component: () => null,
});

type PanelProps = {
  title?: unknown;
  content?: unknown;
  subtitle?: unknown;
  wide?: unknown;
};

export const Columns = defineComponent({
  name: "Columns",
  props: z.object({
    panels: z.array(Panel.ref),
  }),
  description:
    "Panels side by side, two or three to a row; one column on a narrow screen. Use it to put charts next to each other in a dashboard.",
  component: ({ props, renderNode }) => {
    const panels = ((props.panels ?? []) as { props?: PanelProps }[])
      .map((panel) => panel?.props)
      .filter((panel): panel is PanelProps => Boolean(panel));

    if (panels.length === 0) return null;

    const template = panels.map((panel) => (panel.wide === true ? "2fr" : "1fr")).join(" ");

    return (
      <div className="dash-columns-frame">
        <div className="dash-columns" style={{ gridTemplateColumns: template }}>
          {panels.map((panel, index) => (
            <section className="dash-panel" key={index}>
              {text(panel.title) && <h4 className="dash-panel-title">{text(panel.title)}</h4>}
              {text(panel.subtitle) && <p className="dash-panel-subtitle">{text(panel.subtitle)}</p>}
              <div className="dash-panel-content">{renderNode(panel.content as never) as ReactNode}</div>
            </section>
          ))}
        </div>
      </div>
    );
  },
});

// ============================================================
// 큰 숫자 / Stats
// ============================================================

type Tone = "good" | "bad" | "neutral";

export const Stat = defineComponent({
  name: "Stat",
  props: z.object({
    value: z.string().describe('The number as shown, e.g. "$110.4M" or "342%"'),
    label: z.string(),
    change: z.string().optional().describe('The change, e.g. "+12.4%" or "-8.1%"'),
    tone: z
      .enum(["good", "bad", "neutral"])
      .optional()
      .describe(
        "Whether the change is good news; by default a rise is good. A fall in costs or open tickets is good.",
      ),
    icon: z.string().optional().describe('One emoji, e.g. "🌡️" or "💧"'),
    tag: z.string().optional().describe('A word or two about the value, e.g. "Comfortable"'),
  }),
  description:
    'One big number of a StatStrip: value as shown ("$110.4M"), label, change ("+12.4%"). tone says whether the change is good news; by default a rise is good, so set "good" for a fall in costs or open tickets. icon is one emoji shown with the number; tag is a word or two about it ("Partly cloudy", "Humid"). Pass null for a change you skip before an icon or tag.',
  component: () => null,
});

type StatProps = {
  value?: unknown;
  label?: unknown;
  change?: unknown;
  tone?: unknown;
  icon?: unknown;
  tag?: unknown;
};

function toneOf(stat: StatProps): Tone {
  if (stat.tone === "good" || stat.tone === "bad" || stat.tone === "neutral") {
    return stat.tone;
  }

  const change = text(stat.change).trim();

  if (change.startsWith("-") || change.startsWith("−")) return "bad";
  if (change.startsWith("+")) return "good";

  return "neutral";
}

export const StatStrip = defineComponent({
  name: "StatStrip",
  props: z.object({
    stats: z.array(Stat.ref),
  }),
  description:
    "The headline numbers of a dashboard in one row (2 to 6), each with a label and optionally a change, an emoji icon and a tag. Put it first, under the header.",
  component: ({ props }) => {
    const stats = ((props.stats ?? []) as { props?: StatProps }[])
      .map((stat) => stat?.props)
      .filter((stat): stat is StatProps => Boolean(stat));

    if (stats.length === 0) return null;

    return (
      <div className="stat-strip">
        {stats.map((stat, index) => (
          <div className="stat" key={index}>
            <div className="stat-top">
              {text(stat.icon) && (
                <span className="stat-icon" aria-hidden="true">
                  {text(stat.icon)}
                </span>
              )}
              <span className="stat-value">{text(stat.value)}</span>
            </div>
            <div className="stat-label">{text(stat.label)}</div>
            {text(stat.change) && <div className={`stat-change ${toneOf(stat)}`}>{text(stat.change)}</div>}
            {text(stat.tag) && <span className="stat-tag">{text(stat.tag)}</span>}
          </div>
        ))}
      </div>
    );
  },
});

// ============================================================
// 깔때기 / Funnel
// ============================================================

export const FunnelStage = defineComponent({
  name: "FunnelStage",
  props: z.object({
    label: z.string(),
    value: z.number(),
    display: z.string().optional().describe('The value as shown, e.g. "4.2M"; by default the number'),
  }),
  description: "One stage of a FunnelChart.",
  component: () => null,
});

type StageProps = { label?: unknown; value?: unknown; display?: unknown };

function percent(part: number, whole: number): string {
  if (whole <= 0) return "";

  const share = (part / whole) * 100;

  return `${share >= 10 ? share.toFixed(0) : share.toFixed(1)}%`;
}

export const FunnelChart = defineComponent({
  name: "FunnelChart",
  props: z.object({
    stages: z.array(FunnelStage.ref),
  }),
  description:
    "A funnel, e.g. visitors → sign-ups → purchases: one bar per stage, from the largest down, with the share that went on to the next stage.",
  component: ({ props }) => {
    const stages = ((props.stages ?? []) as { props?: StageProps }[])
      .map((stage) => stage?.props)
      .filter((stage): stage is StageProps => Boolean(stage));

    if (stages.length === 0) return null;

    const values = stages.map((stage) => numberOf(stage.value));
    const largest = Math.max(...values, 1);
    const smallest = Math.max(Math.min(...values), 1) / largest;

    // 깔때기는 흔히 백 배 넘게 좁아져 선형 막대가 실처럼 된다. 가장 작은 막대가 가장 큰 막대의 5분의 1쯤 되게
    // 거듭제곱으로 줄인다(완만한 깔때기는 선형 그대로).
    // A funnel often narrows a hundredfold, which a linear scale draws as slivers. The bars shrink by a power of the
    // share instead, chosen so the smallest is about a fifth of the largest; a gentle funnel stays linear.
    const power = smallest < 0.2 ? Math.log(0.2) / Math.log(smallest) : 1;

    return (
      <div className="funnel">
        {stages.map((stage, index) => {
          const value = numberOf(stage.value);
          const width = Math.max((value / largest) ** power * 100, 4);
          const previous = index > 0 ? numberOf(stages[index - 1].value) : 0;

          return (
            <div className="funnel-step" key={index}>
              {index > 0 && previous > 0 && (
                <div className="funnel-drop" aria-label="Share that went on">
                  ↓ {percent(value, previous)}
                </div>
              )}
              <div className="funnel-row">
                <span className="funnel-label">{text(stage.label)}</span>
                <span className="funnel-track">
                  <span
                    className="funnel-bar"
                    style={{
                      width: `${width}%`,
                      opacity: 1 - index * (0.5 / Math.max(stages.length, 2)),
                    }}
                  />
                </span>
                <span className="funnel-value">{text(stage.display) || value.toLocaleString()}</span>
              </div>
            </div>
          );
        })}
      </div>
    );
  },
});

// ============================================================
// 진행 막대 / Progress bar
// ============================================================

export const ProgressBar = defineComponent({
  name: "ProgressBar",
  props: z.object({
    value: z.number(),
    max: z.number().optional().describe("The full bar; 100 by default"),
    label: z.string().optional().describe('The value as shown, e.g. "$299.0M"; by default the number'),
  }),
  description:
    'A value with a bar under it, for a Table cell: Col("Sales", [ProgressBar(299, 300, "$299M"), ...]).',
  component: ({ props }) => {
    const value = numberOf(props.value);
    const max = numberOf(props.max) || 100;
    const width = Math.min(Math.max((value / max) * 100, 0), 100);

    return (
      <span className="progress-cell">
        <span className="progress-cell-label">{text(props.label) || value.toLocaleString()}</span>
        <span className="progress-cell-track">
          <span className="progress-cell-bar" style={{ width: `${width}%` }} />
        </span>
      </span>
    );
  },
});
