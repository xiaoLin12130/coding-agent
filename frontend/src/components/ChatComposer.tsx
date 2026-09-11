import { useState } from "react";

import { useAppStore } from "../store/useAppStore";

export function ChatComposer() {
  const sendChat = useAppStore((state) => state.sendChat);
  const status = useAppStore((state) => state.status);
  const [draft, setDraft] = useState("");

  const submit = () => {
    if (draft.trim() === "") return;
    if (sendChat(draft)) setDraft("");
  };

  return (
    <form
      className="border-t border-edge bg-panel p-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex items-end gap-2">
        <textarea
          value={draft}
          aria-label="Message"
          placeholder="Send a message (Enter to send, Shift+Enter for a newline)"
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
          Send
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {status === "connected"
          ? "WebSocket connected to /ws."
          : "Waiting for the WebSocket connection to /ws."}
      </p>
    </form>
  );
}
