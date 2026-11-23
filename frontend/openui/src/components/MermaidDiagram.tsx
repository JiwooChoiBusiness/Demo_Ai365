// OpenUI 에 없는 컴포넌트: Mermaid 다이어그램(예제 MermaidDiagram.tsx 를 밝은 테마 고정 · 한/영 안내로).
// A component OpenUI does not ship: a Mermaid diagram (the example's MermaidDiagram.tsx, light theme only, with
// Korean and English notes).
//
// - 스트리밍 중에는 코드가 아직 덜 써졌으니 코드로 보여 주고, 답이 끝나면 그린다.
//   While the answer streams the code is half written, so it is shown as code; it is drawn once the answer ends.
// - Mermaid 가 읽지 못하는 코드는 안내와 함께 코드 블록으로 남긴다.
//   Code Mermaid cannot parse stays on screen as a code block, with a note.
// - mermaid 는 크니 첫 다이어그램 때 동적 청크로 내려받는다. / Mermaid is large: a dynamic chunk, fetched on the first diagram.
import { useContext, useEffect, useId, useState } from "react";
import { z } from "zod/v4";
import { defineComponent, useIsStreaming } from "@openuidev/react-lang";

import { LangContext, label } from "../i18n";
import { CodeBlockView, renderNothing } from "./builtins";

type Mermaid = typeof import("mermaid").default;

let mermaidLoading: Promise<Mermaid> | null = null;

function loadMermaid(): Promise<Mermaid> {
  mermaidLoading ??= import("mermaid").then(({ default: mermaid }) => mermaid);

  return mermaidLoading;
}

const FONT = '"Pretendard", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", "Segoe UI", sans-serif';

function configure(mermaid: Mermaid) {
  mermaid.initialize({
    startOnLoad: false,
    // 라벨은 글자만: 모델 코드의 HTML · 스크립트 금지 / labels are text only: no HTML or scripts from the model's code
    securityLevel: "strict",
    theme: "neutral",
    fontFamily: FONT,
  });
}

type DrawState = { status: "waiting" } | { status: "drawn"; svg: string } | { status: "failed" };

function MermaidView({ code, title }: { code: string; title?: string }) {
  const streaming = useIsStreaming();
  const lang = useContext(LangContext);
  const renderId = `ai365oui-mermaid-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [state, setState] = useState<DrawState>({ status: "waiting" });

  useEffect(() => {
    if (streaming || !code.trim()) {
      setState({ status: "waiting" });
      return;
    }

    let stale = false;

    (async () => {
      try {
        const mermaid = await loadMermaid();

        configure(mermaid);

        // 읽지 못하는 코드는 그리기 전에 던진다 / throws on unreadable code before anything is drawn
        await mermaid.parse(code);

        const { svg } = await mermaid.render(renderId, code);

        if (!stale) setState({ status: "drawn", svg });
      } catch {
        // 그리다 만 임시 요소가 body 에 남지 않게 / no half-drawn scratch element left in the body
        document.getElementById(`d${renderId}`)?.remove();
        document.getElementById(renderId)?.remove();

        if (!stale) setState({ status: "failed" });
      }
    })();

    return () => {
      stale = true;
    };
  }, [code, streaming, renderId]);

  return (
    <figure className="mermaid-diagram">
      {title && <figcaption className="mermaid-title">{title}</figcaption>}

      {state.status === "drawn" ? (
        <div
          className="mermaid-svg"
          // securityLevel "strict" 로 정리된 Mermaid 출력 / Mermaid's own output, sanitized by securityLevel "strict"
          dangerouslySetInnerHTML={{ __html: state.svg }}
        />
      ) : (
        <>
          <CodeBlockView props={{ language: "mermaid", codeString: code }} renderNode={renderNothing} />
          <p className="mermaid-note">
            {label(
              lang,
              state.status === "failed"
                ? "This diagram could not be drawn, so its code is shown instead."
                : "Drawing the diagram when the answer is complete…",
            )}
          </p>
        </>
      )}
    </figure>
  );
}

export const MermaidDiagram = defineComponent({
  name: "MermaidDiagram",
  props: z.object({
    code: z
      .string()
      .describe('Valid Mermaid source, e.g. "flowchart TD\\n  A[Start] --> B{Check}\\n  B -->|Yes| C[Done]"'),
    title: z.string().optional().describe("Short caption shown above the diagram"),
  }),
  description:
    "Draws a Mermaid diagram: flowchart, sequence, state, class, ER, gantt, mindmap or timeline. Use it for every flowchart, process or diagram.",
  component: ({ props }) => <MermaidView code={props.code ?? ""} title={props.title} />,
});
