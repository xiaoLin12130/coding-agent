import type { ConnectionStatus } from "../types";

const LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting",
  connected: "Connected",
  disconnected: "Disconnected",
};

const DOT: Record<ConnectionStatus, string> = {
  connecting: "bg-amber-400",
  connected: "bg-emerald-400",
  disconnected: "bg-rose-500",
};

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <span
      data-testid="connection-badge"
      data-status={status}
      className="inline-flex items-center gap-2 rounded-full border border-edge bg-panelAlt px-3 py-1 text-xs text-slate-300"
    >
      <span className={`h-2 w-2 rounded-full ${DOT[status]}`} />
      {LABELS[status]}
    </span>
  );
}
