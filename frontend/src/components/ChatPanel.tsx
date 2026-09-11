import { useAppStore } from "../store/useAppStore";
import { ChatComposer } from "./ChatComposer";
import { ConnectionBadge } from "./ConnectionBadge";
import { MessageList } from "./MessageList";

export function ChatPanel() {
  const status = useAppStore((state) => state.status);
  const messages = useAppStore((state) => state.messages);
  const notices = useAppStore((state) => state.notices);
  const reconnect = useAppStore((state) => state.reconnect);

  return (
    <main
      data-testid="panel-chat"
      className="flex min-w-0 flex-1 flex-col bg-surface"
    >
      <header className="flex items-center justify-between border-b border-edge px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Chat</h2>
          <p className="text-xs text-slate-500">Default Session</p>
        </div>
        <div className="flex items-center gap-2">
          <ConnectionBadge status={status} />
          {status !== "connected" && (
            <button
              type="button"
              onClick={reconnect}
              className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
            >
              Reconnect
            </button>
          )}
        </div>
      </header>

      <MessageList messages={messages} notices={notices} />
      <ChatComposer />
    </main>
  );
}
