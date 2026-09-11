import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../types";

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <li
      data-testid={`message-${message.role}`}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-accent text-white"
            : "border border-edge bg-panelAlt text-slate-100"
        }`}
      >
        {message.content}
      </div>
    </li>
  );
}

export function MessageList({
  messages,
  notices,
}: {
  messages: ChatMessage[];
  notices: string[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    const node = containerRef.current;
    if (node && pinned) node.scrollTop = node.scrollHeight;
  }, [messages, notices, pinned]);

  const handleScroll = () => {
    const node = containerRef.current;
    if (!node) return;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
    setPinned(atBottom);
  };

  const scrollToBottom = () => {
    const node = containerRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    setPinned(true);
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
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {notices.map((notice, index) => (
            <li
              key={`notice-${index}`}
              data-testid="system-notice"
              className="text-center text-xs text-amber-400/90"
            >
              {notice}
            </li>
          ))}
          {messages.length === 0 && notices.length === 0 && (
            <li className="text-center text-sm text-slate-500">
              Send a message to echo it through the backend.
            </li>
          )}
        </ul>
      </div>

      {!pinned && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-edge bg-panelAlt px-3 py-1 text-xs text-slate-300"
        >
          Back to bottom
        </button>
      )}
    </div>
  );
}
