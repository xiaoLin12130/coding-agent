import { eventLabel } from "../../lib/events";
import { formatDuration, formatTime } from "../../lib/format";
import { useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, Spinner, StatusPill } from "../common/Ui";

/** Logs panel: the append-only tool log plus the event stream of this session. */
export function LogsPanel() {
  const logs = useAppStore((state) => state.logs);
  const loadLogs = useAppStore((state) => state.loadLogs);
  const events = useAppStore((state) => state.events);
  const live = useAppStore((state) => state.live);

  const toolCalls = logs.data?.tool_calls ?? [];
  const runtimeEvents = events.length > 0 ? events.map((entry) => entry) : (logs.data?.events ?? []);

  return (
    <div className="flex flex-col gap-3" data-testid="logs-panel">
      <BackendOffline detail={logs.error} />

      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tool log</h3>
        <button
          type="button"
          data-testid="refresh-logs"
          onClick={() => void loadLogs()}
          className="ml-auto rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          Reload
        </button>
      </div>

      {logs.status === "loading" && <Spinner label="Loading logs…" />}
      {logs.status === "error" && <Empty>{logs.error}</Empty>}

      {toolCalls.length === 0 && logs.status !== "loading" ? (
        <Empty>No tool call has been logged yet (runs/tool-calls.jsonl).</Empty>
      ) : (
        <ul data-testid="log-list" className="flex flex-col gap-1">
          {toolCalls.map((entry) => (
            <li
              key={entry.call_id + entry.at}
              data-testid="log-entry"
              className="rounded-lg border border-edge bg-panelAlt px-2 py-1.5 text-[11px]"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-slate-100">{entry.name}</span>
                <StatusPill label={entry.ok ? "ok" : "failed"} tone={entry.ok ? "ok" : "bad"} />
                <span className="text-slate-400">{formatDuration(entry.duration_ms)}</span>
                {entry.confirmed && <StatusPill label="confirmed" tone="info" />}
                {entry.idempotent_replay && <StatusPill label="replay" tone="warn" />}
                {entry.error_code && <span className="font-mono text-rose-300">{entry.error_code}</span>}
                <span className="ml-auto text-slate-500">{formatTime(entry.at)}</span>
              </div>
              <p className="mt-1 truncate font-mono text-slate-400">{entry.arguments_preview}</p>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Events ({runtimeEvents.length})
      </h3>
      {runtimeEvents.length === 0 ? (
        <Empty>No event received yet.</Empty>
      ) : (
        <ul data-testid="event-list" className="flex flex-col gap-1">
          {[...runtimeEvents].reverse().map((entry, index) => (
            <li
              key={"event-" + index}
              data-testid="event-entry"
              className="flex items-center gap-2 rounded-lg border border-edge bg-panelAlt/60 px-2 py-1 text-[11px]"
            >
              <span className="font-mono text-slate-300">
                {"event" in entry ? entry.event : entry.type}
              </span>
              <span className="truncate text-slate-400">
                {"payload" in entry ? eventLabel(entry) : entry.message}
              </span>
              <span className="ml-auto shrink-0 text-slate-600">
                {"received_at" in entry ? formatTime(entry.received_at) : formatTime(entry.at)}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="text-[10px] text-slate-600">
        pending confirmations: {live.confirmations.filter((entry) => entry.answered_with === null).length}
      </p>
    </div>
  );
}
