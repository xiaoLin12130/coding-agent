import { useState } from "react";

import { useAppStore } from "../store/useAppStore";
import { ProjectStateView } from "./ProjectStateView";

const TABS = ["Project State", "Tool Calls", "Memory", "Files", "Logs & Agents"] as const;

type Tab = (typeof TABS)[number];

const PLACEHOLDERS: Record<Exclude<Tab, "Project State">, string> = {
  "Tool Calls": "Tool calls appear here once the Tool layer and its confirmation flow exist.",
  Memory: "Memory entries are read from state/memory.json in a later milestone.",
  Files: "Changed files and diffs arrive with the Executor milestone.",
  "Logs & Agents": "Agent runtime logs arrive with the AgentLoop milestone.",
};

export function WorkbenchPanel() {
  const [tab, setTab] = useState<Tab>("Project State");
  const projectState = useAppStore((state) => state.projectState);
  const stateStatus = useAppStore((state) => state.stateStatus);
  const stateError = useAppStore((state) => state.stateError);
  const memoryCount = useAppStore((state) => state.memoryCount);
  const loadState = useAppStore((state) => state.loadState);

  return (
    <aside
      data-testid="panel-workbench"
      className="flex w-96 shrink-0 flex-col border-l border-edge bg-panel"
    >
      <header className="border-b border-edge px-4 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Workbench</h2>
          <button
            type="button"
            onClick={() => void loadState()}
            className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
          >
            Refresh
          </button>
        </div>
        <nav className="mt-3 flex flex-wrap gap-1">
          {TABS.map((entry) => (
            <button
              key={entry}
              type="button"
              onClick={() => setTab(entry)}
              aria-pressed={tab === entry}
              className={`rounded-lg px-2 py-1 text-xs ${
                tab === entry
                  ? "bg-panelAlt text-slate-100"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {entry}
            </button>
          ))}
        </nav>
      </header>

      <div className="scroll-thin flex-1 overflow-y-auto p-4">
        {tab === "Project State" ? (
          <ProjectStateView
            state={projectState}
            status={stateStatus}
            error={stateError}
            memoryCount={memoryCount}
          />
        ) : (
          <p data-testid="workbench-placeholder" className="text-sm text-slate-500">
            {PLACEHOLDERS[tab]}
          </p>
        )}
      </div>
    </aside>
  );
}
