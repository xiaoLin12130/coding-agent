import { useAppStore } from "../store/useAppStore";
import { backendLabel } from "../lib/format";
import { StatusPill } from "./common/Ui";

const BACKEND_TONE = {
  unknown: "neutral",
  checking: "info",
  online: "ok",
  offline: "bad",
} as const;

/** Slim top bar: backend reachability, provider, and the global actions. */
export function TopBar() {
  const backend = useAppStore((state) => state.backend);
  const backendError = useAppStore((state) => state.backendError);
  const provider = useAppStore((state) => state.settings.data?.provider ?? null);
  const sessions = useAppStore((state) => state.sessions.data ?? []);
  const loadAll = useAppStore((state) => state.loadAll);
  const requestSnapshot = useAppStore((state) => state.requestSnapshot);
  const loadRecovery = useAppStore((state) => state.loadRecovery);

  return (
    <header className="flex items-center gap-3 border-b border-edge bg-panel px-4 py-2">
      <h1 className="text-sm font-semibold tracking-wide text-slate-100">
        编程助手<span className="text-slate-500">· 工作台</span>
      </h1>

      <span
        data-testid="backend-status"
        data-backend={backend}
        title={backendError ?? undefined}
        className="inline-flex items-center gap-2 text-[11px] text-slate-400"
      >
        <StatusPill
          label={backendLabel(backend)}
          tone={BACKEND_TONE[backend]}
          testId="backend-pill"
        />
      </span>

      {provider && (
        <span data-testid="topbar-provider" className="text-[11px] text-slate-500">
          模型提供方 <span className="font-mono text-slate-300">{provider.name || "—"}</span>
          {provider.verified ? "（已验证）" : ""}
        </span>
      )}

      <span className="text-[11px] text-slate-600">{sessions.length} 个会话</span>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          data-testid="topbar-snapshot"
          onClick={() => {
            requestSnapshot();
            void loadRecovery();
          }}
          className="rounded-lg border border-edge px-3 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          快照</button>
        <button
          type="button"
          data-testid="topbar-reload"
          onClick={() => void loadAll()}
          className="rounded-lg border border-edge px-3 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          刷新面板</button>
      </div>
    </header>
  );
}
