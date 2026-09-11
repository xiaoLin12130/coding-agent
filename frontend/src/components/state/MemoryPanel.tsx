import { useMemo, useState } from "react";

import { formatDateTime, truncate } from "../../lib/format";
import { useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { CopyButton } from "../chat/CodeBlock";
import { Empty, Spinner, StatusPill } from "../common/Ui";

/** Memory panel: search, inspect, and the provenance fields of every entry. */
export function MemoryPanel() {
  const memory = useAppStore((state) => state.memory);
  const loadMemory = useAppStore((state) => state.loadMemory);
  const liveMemory = useAppStore((state) => state.live.memory);
  const [query, setQuery] = useState("");
  const [sensitiveOnly, setSensitiveOnly] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const entries = useMemo(
    () => memory.data ?? liveMemory ?? [],
    [memory.data, liveMemory],
  );

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (sensitiveOnly && !entry.sensitive) return false;
      if (needle === "") return true;
      return (
        entry.key.toLowerCase().includes(needle) ||
        entry.value.toLowerCase().includes(needle) ||
        entry.namespace.toLowerCase().includes(needle)
      );
    });
  }, [entries, query, sensitiveOnly]);

  return (
    <div className="flex flex-col gap-3" data-testid="memory-panel">
      <BackendOffline detail={memory.error} />

      <div className="flex items-center gap-2">
        <input
          type="search"
          data-testid="memory-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索记忆"
          aria-label="Search memory"
          className="flex-1 rounded-lg border border-edge bg-surface px-3 py-1.5 text-xs placeholder:text-slate-500 focus:border-accent focus:outline-none"
        />
        <button
          type="button"
          data-testid="refresh-memory"
          onClick={() => void loadMemory()}
          className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent"
        >
          重新加载</button>
      </div>

      <label className="flex items-center gap-2 text-[11px] text-slate-500">
        <input
          type="checkbox"
          data-testid="memory-sensitive-only"
          checked={sensitiveOnly}
          onChange={(event) => setSensitiveOnly(event.target.checked)}
        />
        只看敏感项</label>

      {memory.status === "loading" && entries.length === 0 && <Spinner label="正在加载记忆…" />}
      {memory.status === "error" && entries.length === 0 && <Empty>{memory.error}</Empty>}

      <p className="text-[11px] text-slate-500">
        {visible.length} / {entries.length} 条
      </p>

      <ul data-testid="memory-list" className="flex flex-col gap-2">
        {visible.map((entry) => {
          const id = entry.namespace + "/" + entry.key;
          const open = expanded === id;
          return (
            <li key={id} className="rounded-lg border border-edge bg-panelAlt">
              <button
                type="button"
                data-testid="memory-item"
                onClick={() => setExpanded(open ? null : id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs text-slate-100">{entry.key}</span>
                  <span className="block truncate text-[11px] text-slate-400">
                    {open ? entry.namespace : truncate(entry.value, 60)}
                  </span>
                </span>
                {entry.sensitive && <StatusPill label="敏感" tone="warn" testId="memory-sensitive" />}
              </button>

              {open && (
                <div className="border-t border-edge px-3 py-2">
                  <div className="flex items-start justify-between gap-2">
                    <pre className="scroll-thin max-h-48 flex-1 overflow-auto whitespace-pre-wrap break-words text-[11px] text-slate-200">
                      {entry.value}
                    </pre>
                    <CopyButton text={entry.value} />
                  </div>
                  <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px] text-slate-500">
                    <dt>命名空间</dt>
                    <dd className="font-mono text-slate-300">{entry.namespace}</dd>
                    <dt>来源</dt>
                    <dd className="font-mono text-slate-300">{entry.source || "—"}</dd>
                    <dt>来源轮次</dt>
                    <dd className="font-mono text-slate-300">{entry.source_turn ?? "—"}</dd>
                    <dt>更新者</dt>
                    <dd className="font-mono text-slate-300">{entry.updated_by ?? "—"}</dd>
                    <dt>创建时间</dt>
                    <dd className="font-mono text-slate-300">{formatDateTime(entry.created_at)}</dd>
                    <dt>更新时间</dt>
                    <dd className="font-mono text-slate-300">{formatDateTime(entry.updated_at)}</dd>
                  </dl>
                  <p className="mt-2 text-[10px] text-slate-600">
                    Editing and deleting memory are not part of the frozen contract (no
                    endpoint); this panel is read-only by design.
                  </p>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {visible.length === 0 && <Empty>没有匹配的记忆条目。</Empty>}
    </div>
  );
}
