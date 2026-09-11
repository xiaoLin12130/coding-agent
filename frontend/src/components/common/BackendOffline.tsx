import { useAppStore } from "../../store/useAppStore";

/**
 * The explicit "backend offline" state.
 *
 * The console never shows invented data: when the backend cannot be reached
 * every panel says so instead of rendering an empty or fake view.
 */
export function BackendOffline({ detail }: { detail?: string | null }) {
  const backend = useAppStore((state) => state.backend);
  const backendError = useAppStore((state) => state.backendError);
  const checkBackend = useAppStore((state) => state.checkBackend);
  const loadAll = useAppStore((state) => state.loadAll);

  if (backend !== "offline") return null;

  return (
    <div
      data-testid="backend-offline"
      className="rounded-xl border border-rose-900/70 bg-rose-950/30 p-4 text-sm text-rose-200"
    >
      <p className="font-semibold">Backend offline</p>
      <p className="mt-1 text-xs text-rose-300/90">
        {detail ?? backendError ?? "The console could not reach the backend on the same origin."}
      </p>
      <p className="mt-2 text-xs text-rose-300/70">
        Panels show nothing rather than stale or invented data. Start the backend
        (uvicorn app.main:app --port 8000) and retry.
      </p>
      <button
        type="button"
        data-testid="backend-retry"
        onClick={() => {
          void (async () => {
            const online = await checkBackend();
            if (online) await loadAll();
          })();
        }}
        className="mt-3 rounded-lg border border-rose-800 px-3 py-1 text-xs text-rose-100 hover:bg-rose-900/40"
      >
        Retry
      </button>
    </div>
  );
}
