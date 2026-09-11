import { useState } from "react";

import { asText, formatDuration, formatTime } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import type { JsonValue, ToolCallRecord } from "../../types/ui";
import { Empty, StatusPill } from "../common/Ui";

function commandOf(tool: ToolCallRecord): string {
  const args = tool.args ?? {};
  for (const key of ["command", "cmd", "script", "shell"]) {
    const value = args[key];
    if (typeof value === "string" && value !== "") return value;
  }
  return "";
}

/** Terminal panel: the commands the executor ran, with their output summary. */
export function TerminalPanel() {
  const timeline = useAppStore(selectTimeline);
  const commandsRun = (timeline.projectState?.commands_run ?? []) as JsonValue[];
  const [filter, setFilter] = useState("");

  const rows = timeline.toolCalls.filter((tool) => {
    const needle = filter.trim().toLowerCase();
    if (needle === "") return true;
    return (tool.tool + " " + commandOf(tool) + " " + tool.summary).toLowerCase().includes(needle);
  });

  return (
    <div className="flex flex-col gap-3" data-testid="terminal-panel">
      <input
        type="search"
        data-testid="terminal-filter"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        placeholder="Filter commands"
        aria-label="Filter commands"
        className="w-full rounded-lg border border-edge bg-surface px-3 py-1.5 text-xs placeholder:text-slate-500 focus:border-accent focus:outline-none"
      />

      {commandsRun.length > 0 && (
        <section className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            commands_run (project state)
          </h3>
          <ul className="flex flex-col gap-1">
            {commandsRun.map((entry, index) => (
              <li key={index} className="truncate font-mono text-[11px] text-slate-300">
                {asText(entry)}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Tool activity ({rows.length})
        </h3>

        {rows.length === 0 ? (
          <Empty>No tool call in this session yet.</Empty>
        ) : (
          <ul data-testid="terminal-list" className="flex flex-col gap-2">
            {rows.map((tool) => {
              const command = commandOf(tool);
              return (
                <li
                  key={tool.call_id}
                  data-testid="terminal-entry"
                  data-call-id={tool.call_id}
                  className="rounded-lg border border-edge bg-[#0b0e13] p-2 font-mono text-[11px]"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-400">$</span>
                    <span className="min-w-0 flex-1 whitespace-pre-wrap break-words text-slate-200">
                      {command !== "" ? command : tool.tool + " " + JSON.stringify(tool.args ?? {})}
                    </span>
                    <StatusPill
                      label={tool.status}
                      tone={tool.status === "ok" ? "ok" : tool.status === "failed" ? "bad" : "info"}
                    />
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-500">
                    <span>{formatTime(tool.started_at)}</span>
                    <span>{formatDuration(tool.duration_ms)}</span>
                    {tool.error_code && <span className="text-rose-300">{tool.error_code}</span>}
                  </div>
                  {tool.summary !== "" && (
                    <p className="mt-1 whitespace-pre-wrap break-words text-slate-300">{tool.summary}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
