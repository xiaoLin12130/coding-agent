import { useAppStore } from "../store/useAppStore";
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
        Coding Agent <span className="text-slate-500">· Workbench</span>
      </h1>

      <span
        data-testid="backend-status"
        data-backend={backend}
        title={backendError ?? undefined}
        className="inline-flex items-center gap-2 text-[11px] text-slate-400"
      >
        <StatusPill
          label={backend === "offline" ? "backend offline" : "backend " + backend}
          tone={BACKEND_TONE[backend]}
          testId="backend-pill"
        />
      </span>

      {provider && (
        <span data-testid="topbar-provider" className="text-[11px] text-slate-500">
          provider <span className="font-mono text-slate-300">{provider.name || "—"}</span>
          {provider.verified ? " (verified)" : ""}
        </span>
      )}

      <span className="text-[11px] text-slate-600">{sessions.length} session(s)</span>

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
          Snapshot
        </button>
        <button
          type="button"
          data-testid="topbar-reload"
          onClick={() => void loadAll()}
          className="rounded-lg border border-edge px-3 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          Reload panels
        </button>
      </div>
    </header>
  );
}
