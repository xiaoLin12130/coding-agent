import { useEffect, useRef, useState } from "react";

import { buildTimelineItems } from "../../lib/events";
import { cn, formatTime } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import type { TimelineMessage } from "../../types/ui";
import { CopyButton } from "../chat/CodeBlock";
import { MarkdownView } from "../chat/MarkdownView";
import { ToolCard } from "../tools/ToolCard";
import { ConfirmationCard } from "../tools/ConfirmationCard";

function MessageBubble({
  message,
  onEdit,
  onRetry,
}: {
  message: TimelineMessage;
  onEdit: (text: string) => void;
  onRetry: (text: string) => void;
}) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isTool = message.role === "tool";

  if (isSystem) {
    return (
      <li
        data-testid="message-system"
        className="mx-auto max-w-[85%] rounded-lg border border-edge bg-panelAlt px-3 py-1 text-center text-[11px] text-slate-400"
      >
        {message.content}
      </li>
    );
  }

  return (
    <li
      data-testid={"message-" + message.role}
      className={cn("group flex", isUser ? "justify-end" : "justify-start")}
    >
      <div
        className={cn(
          "max-w-[85%] min-w-0 rounded-2xl px-4 py-2",
          isUser
            ? "bg-accent/90 text-white"
            : isTool
              ? "border border-edge bg-panelAlt/60 text-slate-200"
              : "border border-edge bg-panelAlt text-slate-100",
        )}
      >
        {isTool && message.tool_name && (
          <p className="mb-1 font-mono text-[11px] text-slate-400">{message.tool_name}</p>
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{message.content}</p>
        ) : (
          <MarkdownView content={message.content} />
        )}

        {message.streaming && (
          <span data-testid="streaming-cursor" className="ml-1 inline-block h-3 w-1 animate-pulse bg-accent align-middle" />
        )}

        <div className="mt-1 flex items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <span className="text-[10px] text-slate-500">{formatTime(message.created_at)}</span>
          <CopyButton text={message.content} />
          {isUser && (
            <>
              <button
                type="button"
                data-testid="message-retry"
                onClick={() => onRetry(message.content)}
                className="rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent hover:text-slate-200"
              >
                Retry
              </button>
              <button
                type="button"
                data-testid="message-edit"
                onClick={() => onEdit(message.content)}
                className="rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent hover:text-slate-200"
              >
                Edit
              </button>
            </>
          )}
        </div>
      </div>
    </li>
  );
}

export function MessageList({
  onEdit,
  onRetry,
}: {
  onEdit: (text: string) => void;
  onRetry: (text: string) => void;
}) {
  const timeline = useAppStore(selectTimeline);
  const respondConfirm = useAppStore((state) => state.respondConfirm);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const items = buildTimelineItems(timeline);

  useEffect(() => {
    const node = containerRef.current;
    if (node && pinned) node.scrollTop = node.scrollHeight;
  }, [items.length, pinned, timeline.notices.length]);

  const handleScroll = () => {
    const node = containerRef.current;
    if (!node) return;
    setPinned(node.scrollHeight - node.scrollTop - node.clientHeight < 40);
  };

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        data-testid="message-list"
        className="scroll-thin h-full overflow-y-auto px-4 py-4"
      >
        <ul className="flex flex-col gap-3">
          {items.map((item) => {
            if (item.kind === "message") {
              return (
                <MessageBubble
                  key={"m-" + item.message.id}
                  message={item.message}
                  onEdit={onEdit}
                  onRetry={onRetry}
                />
              );
            }
            if (item.kind === "tool") {
              return (
                <li key={"t-" + item.tool.call_id + "-" + item.seq}>
                  <ToolCard record={item.tool} />
                </li>
              );
            }
            // An unanswered confirmation is answered in the dialog, not twice.
            if (item.confirmation.answered_with === null) return null;
            return (
              <li key={"c-" + item.confirmation.request_id}>
                <ConfirmationCard confirmation={item.confirmation} onChoose={respondConfirm} />
              </li>
            );
          })}

          {timeline.notices.map((notice, index) => (
            <li
              key={"notice-" + index}
              data-testid="system-notice"
              className="text-center text-xs text-amber-400/90"
            >
              {notice}
            </li>
          ))}

          {items.length === 0 && timeline.notices.length === 0 && (
            <li className="text-center text-sm text-slate-500">
              Ask the agent to do something, or send a chat message to echo it through the backend.
            </li>
          )}
        </ul>
      </div>

      {!pinned && (
        <button
          type="button"
          data-testid="back-to-bottom"
          onClick={() => {
            const node = containerRef.current;
            if (node) node.scrollTop = node.scrollHeight;
            setPinned(true);
          }}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-edge bg-panelAlt px-3 py-1 text-xs text-slate-300"
        >
          Back to bottom
        </button>
      )}
    </div>
  );
}
