import { useState } from "react";

import { connectionLabel } from "../../lib/format";
import { useAppStore } from "../../store/useAppStore";
import type { RunMode } from "../../types/ui";

type ComposerMode = "run" | "chat";

/**
 * One input for both ways of talking to the backend:
 *   run  -> {"type":"run","task":...,"mode":"single|multi"}
 *   chat -> {"type":"ask","content":"..."}   (the configured model answers,
 *                                              streamed back as assistant_delta)
 */
export function ChatComposer({
  draft,
  setDraft,
}: {
  draft: string;
  setDraft: (value: string) => void;
}) {
  const startRun = useAppStore((state) => state.startRun);
  const sendChat = useAppStore((state) => state.sendChat);
  const stopRun = useAppStore((state) => state.stopRun);
  const connection = useAppStore((state) => state.connection);
  const running = useAppStore((state) => state.live.running);
  const [mode, setMode] = useState<ComposerMode>("run");
  const [selected, setSelected] = useState<RunMode>("single");

  const submit = () => {
    const text = draft.trim();
    if (text === "") return;
    if (mode === "chat") {
      if (sendChat(text)) setDraft("");
      return;
    }
    void startRun({ task: text, mode: selected }).then((accepted) => {
      if (accepted) setDraft("");
    });
  };

  return (
    <form
      className="border-t border-edge bg-panel p-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-lg border border-edge">
          {(["run", "chat"] as ComposerMode[]).map((entry) => (
            <button
              key={entry}
              type="button"
              data-testid={"composer-mode-" + entry}
              aria-pressed={mode === entry}
              onClick={() => setMode(entry)}
              className={
                "px-2 py-1 text-[11px] " +
                (mode === entry ? "bg-panelAlt text-slate-100" : "text-slate-400 hover:text-slate-200")
              }
            >
              {entry === "run" ? "智能体运行" : "询问模型"}
            </button>
          ))}
        </div>

        {mode === "run" && (
          <select
            aria-label="运行模式"
            data-testid="composer-run-mode"
            value={selected}
            onChange={(event) => setSelected(event.target.value as RunMode)}
            className="rounded-lg border border-edge bg-surface px-2 py-1 text-[11px] text-slate-300"
          >
            <option value="single">single</option>
            <option value="multi">multi</option>
          </select>
        )}

        {running && (
          <button
            type="button"
            data-testid="stop-run"
            onClick={() => void stopRun()}
            className="rounded-lg border border-rose-800 bg-rose-950/40 px-2 py-1 text-[11px] text-rose-200"
          >
            停止</button>
        )}

        <span className="ml-auto text-[11px] text-slate-500">
          {connection === "connected" ? "连接正常" : "连接" + connectionLabel(connection)}
        </span>
      </div>

      <div className="flex items-end gap-2">
        <textarea
          value={draft}
          aria-label="消息"
          placeholder={
            mode === "run"
              ? "Describe the task for the agent (Enter to send, Shift+Enter for a newline)"
              : "Ask the configured model a question (the answer streams in)"
          }
          rows={2}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          className="scroll-thin max-h-40 flex-1 resize-y rounded-xl border border-edge bg-surface px-3 py-2 text-sm placeholder:text-slate-500 focus:border-accent focus:outline-none"
        />
        <button
          type="submit"
          disabled={draft.trim() === ""}
          className="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {mode === "run" ? "运行" : "发送"}
        </button>
      </div>
    </form>
  );
}
