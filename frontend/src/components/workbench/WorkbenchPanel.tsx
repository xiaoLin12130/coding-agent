import { useAppStore } from "../../store/useAppStore";
import { AgentsPanel } from "../state/AgentsPanel";
import { FilesPanel } from "../state/FilesPanel";
import { LogsPanel } from "../state/LogsPanel";
import { MemoryPanel } from "../state/MemoryPanel";
import { ProjectStateView } from "../state/ProjectStateView";
import { TerminalPanel } from "../state/TerminalPanel";
import { ObservabilityPanel } from "../observability/ObservabilityPanel";
import { SettingsPanel } from "../settings/SettingsPanel";
import { ToolCard } from "../tools/ToolCard";

export type WorkbenchTab =
  | "State"
  | "Tools"
  | "Memory"
  | "Files"
  | "Terminal"
  | "Logs"
  | "Agents"
  | "Observe"
  | "Settings";

const TABS: WorkbenchTab[] = [
  "State",
  "Tools",
  "Memory",
  "Files",
  "Terminal",
  "Logs",
  "Agents",
  "Observe",
  "Settings",
];

function ToolsTab() {
  const toolCalls = useAppStore((state) => state.live.toolCalls);
  const pending = useAppStore((state) =>
    state.live.confirmations.filter((entry) => entry.answered_with === null).length,
  );

  return (
    <div className="flex flex-col gap-3" data-testid="tools-tab">
      <p className="text-[11px] text-slate-500">
        {toolCalls.length} tool call(s) in this session · {pending} waiting for confirmation
      </p>
      {toolCalls.length === 0 ? (
        <p className="text-xs text-slate-500">
          Tool cards appear as soon as a tool_call event arrives and pair with its tool_result by
          call_id.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {[...toolCalls].reverse().map((tool) => (
            <ToolCard key={tool.call_id} record={tool} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Right column: every workbench panel behind one tab strip. */
export function WorkbenchPanel({
  tab,
  setTab,
}: {
  tab: WorkbenchTab;
  setTab: (tab: WorkbenchTab) => void;
}) {
  const loadAll = useAppStore((state) => state.loadAll);

  const pending = useAppStore((state) =>
    state.live.confirmations.filter((entry) => entry.answered_with === null).length,
  );

  return (
    <aside
      data-testid="panel-workbench"
      className="flex w-[26rem] shrink-0 flex-col border-l border-edge bg-panel"
    >
      <header className="border-b border-edge px-4 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Workbench</h2>
          <div className="flex items-center gap-2">
            {pending > 0 && (
              <span
                data-testid="pending-confirmations"
                className="rounded-full border border-amber-800 bg-amber-950/40 px-2 py-0.5 text-[11px] text-amber-200"
              >
                {pending} confirm
              </span>
            )}
            <button
              type="button"
              data-testid="refresh-workbench"
              onClick={() => void loadAll()}
              className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
            >
              Refresh
            </button>
          </div>
        </div>

        <nav className="mt-3 flex flex-wrap gap-1" aria-label="Workbench tabs">
          {TABS.map((entry) => (
            <button
              key={entry}
              type="button"
              role="tab"
              aria-selected={tab === entry}
              data-testid={"tab-" + entry.toLowerCase()}
              onClick={() => setTab(entry)}
              className={
                "rounded-lg px-2 py-1 text-xs " +
                (tab === entry ? "bg-panelAlt text-slate-100" : "text-slate-400 hover:text-slate-200")
              }
            >
              {entry}
            </button>
          ))}
        </nav>
      </header>

      <div className="scroll-thin flex-1 overflow-y-auto p-4">
        {tab === "State" && <ProjectStateView />}
        {tab === "Tools" && <ToolsTab />}
        {tab === "Memory" && <MemoryPanel />}
        {tab === "Files" && <FilesPanel />}
        {tab === "Terminal" && <TerminalPanel />}
        {tab === "Logs" && <LogsPanel />}
        {tab === "Agents" && <AgentsPanel />}
        {tab === "Observe" && <ObservabilityPanel />}
        {tab === "Settings" && <SettingsPanel />}
      </div>
    </aside>
  );
}
