// 섬 하나(채팅 답 하나)의 React 뿌리. 프로그램이면 OpenUI Renderer 로, 아니면 마크다운으로 그린다(예제 AnswerView 방식).
// The React root of one island (one chat answer). A program renders through OpenUI's Renderer; anything else as
// markdown (the example's AnswerView).
//
// - 동작: continue_conversation → opts.onAction({type, text}) (폼 값은 formAnswers 로 글에 붙임), open_url → 링크 규칙
//   Actions: continue_conversation → opts.onAction({type, text}) (form values appended by formAnswers),
//   open_url → the link rule
// - 링크: 뿌리의 캡처 단계에서 <a> 의 기본 동작을 막고 링크 규칙을 쓴다(포털 안 클릭도 React 트리로 지나간다)
//   Links: the root's capture phase prevents <a>'s default and applies the link rule (clicks in portals pass
//   through the React tree too)
// - 렌더 오류: 스트리밍이 끝난 뒤 opts.onError(errors), 화면에는 opts.debug 일 때만
//   Render errors: opts.onError(errors) once streaming is over; on screen only with opts.debug
import { Component, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ErrorInfo, MouseEvent as ReactMouseEvent, ReactNode, SyntheticEvent } from "react";
import { Renderer } from "@openuidev/react-lang";
import type { ActionEvent, OpenUIError } from "@openuidev/react-lang";

import { TextContentView, renderNothing } from "./components/builtins";
import { withFormAnswers } from "./formAnswers";
import { LangContext, label, toLang } from "./i18n";
import { library } from "./library";
import { enterIsland, followLink, type LinkContext } from "./links";
import { isProgram, plainText, toProgram } from "./program";

/** render() 의 opts / The opts of render(). */
export type IslandOptions = {
  streaming?: boolean;
  lang?: string;
  onAction?: (event: { type: "continue_conversation"; text: string }) => void;
  onLink?: (url: string, el: HTMLElement) => void;
  onError?: (errors: unknown[]) => void;
  debug?: boolean;
};

type CrashProps = { resetKey: string; fallback: ReactNode; onCrash: (error: unknown) => void; children: ReactNode };
type CrashState = { failed: boolean; key: string };

/** 렌더가 통째로 깨지면 평문으로(새 프로그램이 오면 다시 시도) / Plain text when rendering breaks (retried on a new program). */
class CrashGuard extends Component<CrashProps, CrashState> {
  state: CrashState = { failed: false, key: this.props.resetKey };

  static getDerivedStateFromError(): Partial<CrashState> {
    return { failed: true };
  }

  static getDerivedStateFromProps(props: CrashProps, state: CrashState): Partial<CrashState> | null {
    return props.resetKey !== state.key ? { failed: false, key: props.resetKey } : null;
  }

  componentDidCatch(error: unknown, _info: ErrorInfo) {
    this.props.onCrash(error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="ai365-oui-md">
      <TextContentView props={{ text }} renderNode={renderNothing} />
    </div>
  );
}

export function Island({ el, program, opts }: { el: HTMLElement; program: string; opts: IslandOptions }) {
  const lang = toLang(opts.lang);
  const streaming = opts.streaming === true;
  const optsRef = useRef(opts);
  const langRef = useRef(lang);

  optsRef.current = opts;
  langRef.current = lang;

  const ctx = useMemo<LinkContext>(() => ({ el, onLink: (url, target) => optsRef.current.onLink?.(url, target) }), [el]);
  const prog = useMemo(() => toProgram(program), [program]);
  const asMarkdown = !streaming && !!prog && !isProgram(prog);

  const progRef = useRef(prog);

  progRef.current = prog;

  // 오류는 그 프로그램에만 딸린다(다른 프로그램 · 마크다운이 오면 자연히 없어진다)
  // errors belong to their program (gone once another program or markdown arrives)
  const [reported, setReported] = useState<{ key: string; list: OpenUIError[] }>({ key: "", list: [] });
  const errors = reported.key === prog ? reported.list : [];
  const [crashed, setCrashed] = useState<{ key: string; message: string } | null>(null);
  const crash = crashed && crashed.key === prog ? crashed.message : null;

  const handleAction = useCallback(
    (event: ActionEvent) => {
      if (event.type === "continue_conversation") {
        const text =
          typeof event.params?.message === "string" ? event.params.message : String(event.humanFriendlyMessage ?? "");
        // 폼 안의 단추만 폼 값을 붙인다(후속 질문 칩은 글 그대로) / only buttons inside a form send its values
        const message = event.formName ? withFormAnswers(text, event.formState, langRef.current) : text;

        if (message.trim()) optsRef.current.onAction?.({ type: "continue_conversation", text: message });
      } else if (event.type === "open_url") {
        followLink(event.params?.url, ctx);
      }
    },
    [ctx],
  );

  const handleErrors = useCallback((next: OpenUIError[]) => {
    setReported({ key: progRef.current, list: next });

    // Renderer 는 스트리밍이 끝난 뒤에만 오류를 모은다 / the Renderer only collects errors once streaming is over
    if (next.length > 0) optsRef.current.onError?.(next);
  }, []);

  const handleCrash = useCallback((error: unknown) => {
    setCrashed({ key: progRef.current, message: error instanceof Error ? error.message : String(error) });
  }, []);

  // 통째로 깨진 경우도 스트리밍이 끝난 뒤에 알린다 / a crash is reported too, once streaming is over
  useEffect(() => {
    if (crash && !streaming) {
      optsRef.current.onError?.([{ source: "runtime", code: "render-error", message: crash }]);
    }
  }, [crash, streaming]);

  const onCapture = useCallback(
    (event: SyntheticEvent) => {
      enterIsland(ctx);

      if (event.type !== "click" && event.type !== "auxclick") return;
      if (event.type === "auxclick" && (event as ReactMouseEvent).button !== 1) return;

      const target = event.target as Element | null;
      const anchor = target?.closest?.("a[href]") ?? null;

      if (!anchor) return;

      // <a> 는 링크 규칙으로만(사내 ai365:// 는 브라우저가 열지 않게) / anchors only by the rule (never a browser ai365://)
      event.preventDefault();
      followLink(anchor.getAttribute("href"), ctx);
    },
    [ctx],
  );

  const fallbackText = useMemo(() => plainText(prog) || prog, [prog]);
  const fallback = <Markdown text={fallbackText} />;

  let content: ReactNode = null;

  if (asMarkdown) {
    content = <Markdown text={String(program)} />;
  } else if (prog) {
    content = (
      <Renderer
        response={prog}
        library={library}
        isStreaming={streaming}
        onAction={handleAction}
        onError={handleErrors}
      />
    );
  }

  const shown = opts.debug === true && !streaming;
  const count = errors.length + (crash ? 1 : 0);

  return (
    <LangContext.Provider value={lang}>
      <div
        className="ai365-oui-root"
        lang={lang}
        data-lang={lang}
        onClickCapture={onCapture}
        onAuxClickCapture={onCapture}
        onKeyDownCapture={onCapture}
        onPointerDownCapture={onCapture}
      >
        <CrashGuard resetKey={prog} fallback={fallback} onCrash={handleCrash}>
          {content}
        </CrashGuard>

        {shown && count > 0 && (
          <details className="ai365-oui-errors">
            <summary>
              {lang === "en" ? `${count} part(s) could not be rendered` : `${count}개 부분을 표시하지 못했습니다`}
            </summary>
            {crash && <p>{label(lang, "This answer could not be shown as a card, so its text is shown instead.")}</p>}
            <pre>{JSON.stringify(crash ? [...errors, { code: "render-error", message: crash }] : errors, null, 2)}</pre>
          </details>
        )}
      </div>
    </LangContext.Provider>
  );
}
