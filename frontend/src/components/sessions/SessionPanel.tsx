import { useMemo, useState } from "react";

import { formatRelative, truncate } from "../../lib/format";
import { useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, Spinner, StatusPill } from "../common/Ui";

/** Left column: sessions (new / search / switch / archive) and the provider. */
export function SessionPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  const sessions = useAppStore((state) => state.sessions);
  const activeSessionId = useAppStore((state) => state.activeSessionId);
  const query = useAppStore((state) => state.sessionQuery);
  const setSessionQuery = useAppStore((state) => state.setSessionQuery);
  const switchSession = useAppStore((state) => state.switchSession);
  const newSession = useAppStore((state) => state.newSession);
  const archiveSession = useAppStore((state) => state.archiveSession);
  const settings = useAppStore((state) => state.settings);
  const [archivedVisible, setArchivedVisible] = useState(false);

  const items = sessions.data ?? [];
  const needle = query.trim().toLowerCase();
  const visible = useMemo(() => {
    const filtered = archivedVisible ? items : items.filter((entry) => !entry.archived);
    if (needle === "") return filtered;
    return filtered.filter((entry) =>
      (entry.title + " " + entry.id).toLowerCase().includes(needle),
    );
  }, [items, needle, archivedVisible]);

  const provider = settings.data?.provider ?? null;

  return (
    <aside
      data-testid="panel-sessions"
      className="flex w-72 shrink-0 flex-col gap-3 border-r border-edge bg-panel p-4"
    >
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold tracking-wide text-slate-200">会话</h1>
        <button
          type="button"
          data-testid="new-session"
          onClick={() => void newSession()}
          className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          新建</button>
      </div>

      <input
        type="search"
        value={query}
        onChange={(event) => setSessionQuery(event.target.value)}
        placeholder="搜索会话"
        aria-label="搜索会话"
        className="w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm placeholder:text-slate-500 focus:border-accent focus:outline-none"
      />

      <label className="flex items-center gap-2 text-[11px] text-slate-500">
        <input
          type="checkbox"
          data-testid="show-archived"
          checked={archivedVisible}
          onChange={(event) => setArchivedVisible(event.target.checked)}
        />
        显示已归档</label>

      <BackendOffline detail={sessions.error} />

      <div className="scroll-thin -mx-1 flex-1 overflow-y-auto px-1">
        {sessions.status === "loading" && items.length === 0 && <Spinner label="正在加载会话…" />}
        {sessions.status === "error" && items.length === 0 && (
          <Empty>No sessions: {sessions.error}</Empty>
        )}

        <ul data-testid="session-list" className="flex flex-col gap-1">
          {visible.map((session) => {
            const active = session.id === activeSessionId;
            return (
              <li key={session.id} className="group flex items-stretch gap-1">
                <button
                  type="button"
                  data-testid="session-item"
                  data-session-id={session.id}
                  data-active={active}
                  aria-current={active}
                  onClick={() => void switchSession(session.id)}
                  className={
                    "min-w-0 flex-1 rounded-lg border px-3 py-2 text-left " +
                    (active
                      ? "border-accent/60 bg-panelAlt text-slate-100"
                      : "border-transparent bg-panelAlt/50 text-slate-300 hover:border-edge")
                  }
                >
                  <span className="block truncate text-sm">{session.title || session.id}</span>
                  <span className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">
                    <span>{session.message_count} 条消息</span>
                    <span>· {session.turn_count} 轮</span>
                    <span>· {formatRelative(session.updated_at)}</span>
                  </span>
                  {session.archived && (
                    <span className="mt-1 inline-block">
                      <StatusPill label="已归档" tone="warn" />
                    </span>
                  )}
                  {session.rotated_from && (
                    <span className="mt-1 block truncate text-[10px] text-slate-600">
                      接续自 {truncate(session.rotated_from, 28)}
                    </span>
                  )}
                </button>
                {!session.archived && (
                  <button
                    type="button"
                    title="归档此会话"
                    data-testid="archive-session"
                    onClick={() => void archiveSession(session.id)}
                    className="rounded-lg border border-transparent px-2 text-[11px] text-slate-500 opacity-0 hover:border-edge hover:text-slate-200 group-hover:opacity-100"
                  >
                    归档</button>
                )}
              </li>
            );
          })}
        </ul>

        {visible.length === 0 && sessions.status !== "loading" && (
          <Empty>没有匹配的会话。</Empty>
        )}
      </div>

      <section
        data-testid="provider-card"
        className="rounded-lg border border-edge bg-panelAlt p-3 text-xs text-slate-400"
      >
        <p className="font-medium text-slate-300">模型提供方</p>
        {provider ? (
          <dl className="mt-1 flex flex-col gap-0.5">
            <div className="flex items-center justify-between gap-2">
              <dt>名称</dt>
              <dd data-testid="provider-name" className="truncate font-mono text-slate-200">
                {provider.name || "—"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt>地址</dt>
              <dd className="truncate font-mono text-slate-300">{provider.url || "—"}</dd>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <StatusPill
                label={provider.verified ? "已验证" : "未验证"}
                tone={provider.verified ? "ok" : "warn"}
                testId="provider-verified"
              />
              {(provider.profiles ?? []).length > 0 && (
                <span className="truncate text-[10px] text-slate-500">
                  {(provider.profiles ?? []).join(", ")}
                </span>
              )}
            </div>
          </dl>
        ) : (
          <p className="mt-1">{settings.status === "error" ? settings.error : "加载中…"}</p>
        )}

        <button
          type="button"
          data-testid="open-settings"
          onClick={onOpenSettings}
          className="mt-3 w-full rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          设置</button>
      </section>
    </aside>
  );
}
