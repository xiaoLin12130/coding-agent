import { useState } from "react";

import { formatDuration, statusLabel } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import { ChatComposer } from "./ChatComposer";
import { ConnectionBadge } from "./ConnectionBadge";
import { MessageList } from "./MessageList";
import { ConfirmationDialog } from "../tools/ConfirmationDialog";
import { StatusPill } from "../common/Ui";

export function ChatPanel() {
  const status = useAppStore((state) => state.connection);
  const reconnect = useAppStore((state) => state.reconnect);
  const timeline = useAppStore(selectTimeline);
  const sessions = useAppStore((state) => state.sessions);
  const activeSessionId = useAppStore((state) => state.activeSessionId);
  const startRun = useAppStore((state) => state.startRun);
  const replay = useAppStore((state) => state.replay);
  const eventCount = useAppStore((state) => state.events.length);
  const stopReplay = useAppStore((state) => state.stopReplay);
  const [draft, setDraft] = useState("");

  const active = (sessions.data ?? []).find((entry) => entry.id === activeSessionId);
  const running = timeline.running;
  const toolCount = timeline.toolCalls.length;

  return (
    <main data-testid="panel-chat" className="relative flex min-w-0 flex-1 flex-col bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-edge px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-slate-200">对话</h2>
          <p className="truncate text-xs text-slate-500">
            {active ? active.title || active.id : activeSessionId ?? "无会话"}
          </p>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {running && (
            <StatusPill label={"运行: " + statusLabel(timeline.runStatus)} tone="info" testId="run-status" />
          )}
          {toolCount > 0 && (
            <StatusPill label={toolCount + " 次工具调用"} tone="neutral" />
          )}
          {replay.active && (
            <button
              type="button"
              data-testid="replay-banner"
              onClick={stopReplay}
              className="rounded-full border border-sky-900 bg-sky-950/40 px-2 py-0.5 text-[11px] text-sky-200"
            >
              回放 #{replay.index + 1} — 回到实时
            </button>
          )}
          <ConnectionBadge status={status} />
          {status !== "connected" && (
            <button
              type="button"
              onClick={reconnect}
              className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
            >
              重新连接</button>
          )}
        </div>
      </header>

      <MessageList
        onEdit={(text) => setDraft(text)}
        onRetry={(text) => {
          void startRun({ task: text, mode: "single" });
        }}
      />

      <ChatComposer draft={draft} setDraft={setDraft} />

      <ConfirmationDialog />

      <p className="border-t border-edge px-4 py-1 text-[10px] text-slate-600">
        最近运行：{timeline.runId ?? "—"} · 状态 {statusLabel(timeline.runStatus)} · 事件 {eventCount}
        {timeline.toolCalls.length > 0 && (
          <> · 最慢的工具 {formatDuration(Math.max(...timeline.toolCalls.map((tool) => tool.duration_ms ?? 0)))}</>
        )}
      </p>
    </main>
  );
}
