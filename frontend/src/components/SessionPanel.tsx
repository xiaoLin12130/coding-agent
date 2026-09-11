import { useMemo, useState } from "react";

type SessionEntry = {
  id: string;
  title: string;
  subtitle: string;
};

// M0 has a single implicit session; the list is a skeleton for M1+.
const SESSIONS: SessionEntry[] = [
  { id: "default", title: "Default Session", subtitle: "current" },
];

export function SessionPanel() {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return SESSIONS;
    return SESSIONS.filter((session) =>
      session.title.toLowerCase().includes(needle),
    );
  }, [query]);

  return (
    <aside
      data-testid="panel-sessions"
      className="flex w-64 shrink-0 flex-col gap-4 border-r border-edge bg-panel p-4"
    >
      <h1 className="text-sm font-semibold tracking-wide text-slate-200">
        Sessions
      </h1>

      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search sessions"
        aria-label="Search sessions"
        className="w-full rounded-lg border border-edge bg-surface px-3 py-2 text-sm placeholder:text-slate-500 focus:border-accent focus:outline-none"
      />

      <ul className="flex flex-col gap-1">
        {visible.map((session) => (
          <li key={session.id}>
            <button
              type="button"
              className="w-full rounded-lg bg-panelAlt px-3 py-2 text-left text-sm text-slate-200"
            >
              <span className="block truncate">{session.title}</span>
              <span className="block text-xs text-slate-500">
                {session.subtitle}
              </span>
            </button>
          </li>
        ))}
        {visible.length === 0 && (
          <li className="px-1 text-xs text-slate-500">No matching session.</li>
        )}
      </ul>

      <div className="mt-auto rounded-lg border border-edge bg-panelAlt p-3 text-xs text-slate-400">
        <p className="font-medium text-slate-300">Provider</p>
        <p className="mt-1">Not configured (planned for a later milestone).</p>
        <p className="mt-3 font-medium text-slate-300">Settings</p>
        <p className="mt-1">Placeholder.</p>
      </div>
    </aside>
  );
}
