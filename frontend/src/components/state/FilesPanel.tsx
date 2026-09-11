import { useMemo, useState } from "react";

import { basename } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import type { EventRecord, ToolCallRecord } from "../../types/ui";
import { DiffView, parseUnifiedDiff } from "../chat/DiffView";
import { Empty, StatusPill } from "../common/Ui";

const DIFF_KEYS = ["diff", "patch", "unified_diff", "unified", "changes"];

/** Pull a unified diff out of a tool event payload, if the backend sent one. */
function findDiff(events: EventRecord[], file: string | null): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const payload = events[index].payload;
    const candidates = [payload, (payload.data ?? {}) as Record<string, unknown>];
    for (const candidate of candidates) {
      for (const key of DIFF_KEYS) {
        const value = candidate[key];
        if (typeof value === "string" && value.includes("@@")) {
          if (file === null || JSON.stringify(payload).includes(file)) return value;
        }
      }
    }
  }
  return null;
}

function touchesFile(tool: ToolCallRecord, file: string): boolean {
  const haystack = JSON.stringify(tool.args ?? {});
  return haystack.includes(file) || haystack.includes(basename(file));
}

/** Files panel: what changed, who changed it, and any diff we were given. */
export function FilesPanel() {
  const timeline = useAppStore(selectTimeline);
  const events = useAppStore((state) => state.events);
  const [selected, setSelected] = useState<string | null>(null);

  const files = timeline.projectState?.files_changed ?? [];
  const active = selected ?? files[0] ?? null;

  const owners = useMemo(
    () => timeline.toolCalls.filter((tool) => (active ? touchesFile(tool, active) : false)),
    [timeline.toolCalls, active],
  );

  const diffText = useMemo(() => {
    const carried = timeline.toolCalls.find(
      (tool) => tool.diff !== null && (active === null || touchesFile(tool, active)),
    );
    return carried?.diff ?? findDiff(events, active);
  }, [events, active, timeline.toolCalls]);
  const diffLines = useMemo(() => (diffText ? parseUnifiedDiff(diffText) : []), [diffText]);

  if (files.length === 0) {
    return (
      <div className="flex flex-col gap-3" data-testid="files-panel">
        <Empty>
          No file has been changed in this session yet (project state reports an empty
          files_changed list).
        </Empty>
        <p className="text-[11px] text-slate-600">
          Diff view: a unified diff is rendered here as soon as a tool result carries one.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="files-panel">
      <p className="text-[11px] text-slate-500">{files.length} changed file(s)</p>

      <ul data-testid="files-list" className="flex flex-col gap-1">
        {files.map((file) => (
          <li key={file}>
            <button
              type="button"
              data-testid="file-item"
              data-file={file}
              aria-pressed={file === active}
              onClick={() => setSelected(file)}
              className={
                "w-full rounded-lg border px-3 py-2 text-left " +
                (file === active ? "border-accent/60 bg-panelAlt" : "border-edge bg-panelAlt/40")
              }
            >
              <span className="block truncate font-mono text-xs text-slate-200">{basename(file)}</span>
              <span className="block truncate text-[10px] text-slate-500">{file}</span>
            </button>
          </li>
        ))}
      </ul>

      {active && (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Touched by
          </h3>
          {owners.length === 0 ? (
            <Empty>No tool call in the recorded stream touched this file.</Empty>
          ) : (
            <ul className="flex flex-col gap-1">
              {owners.map((tool) => (
                <li key={tool.call_id} className="flex items-center gap-2 text-[11px]">
                  <span className="font-mono text-slate-200">{tool.tool}</span>
                  <StatusPill
                    label={tool.status}
                    tone={tool.status === "ok" ? "ok" : tool.status === "failed" ? "bad" : "info"}
                  />
                  <span className="truncate text-slate-500">{tool.summary}</span>
                </li>
              ))}
            </ul>
          )}

          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Diff</h3>
          {diffText ? (
            <DiffView diff={diffLines} title={basename(active)} />
          ) : (
            <Empty>
              The stream carried no unified diff for this file. The backend contract has no
              file-content endpoint, so the console does not invent one.
            </Empty>
          )}
        </section>
      )}
    </div>
  );
}
