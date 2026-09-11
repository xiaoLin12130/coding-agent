import { useState } from "react";

import { cn, formatDuration, formatJson, formatTime } from "../../lib/format";
import type { ToolCallRecord } from "../../types/ui";
import { CopyButton } from "../chat/CodeBlock";
import { DiffView, parseUnifiedDiff } from "../chat/DiffView";
import { RiskPill, StatusPill } from "../common/Ui";

const STATUS_LABEL: Record<ToolCallRecord["status"], string> = {
  running: "running",
  ok: "ok",
  failed: "failed",
};

/**
 * One Tool Card: tool, parameters, status, risk, duration and result summary.
 * It is always built from a real tool_call/tool_result pair (matched on
 * call_id) — nothing here is synthesised when the stream is silent.
 */
export function ToolCard({ record, defaultOpen = false }: { record: ToolCallRecord; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const tone = record.status === "ok" ? "ok" : record.status === "failed" ? "bad" : "info";
  const params = formatJson(record.args);
  const hasParams = params !== "" && params !== "{}";
  // A one line parameter preview keeps the card useful without expanding it.
  const preview = Object.entries(record.args ?? {})
    .slice(0, 3)
    .map(([key, value]) => {
      const text = typeof value === "string" ? value : formatJson(value);
      return key + "=" + (text.length > 60 ? text.slice(0, 59) + "…" : text);
    })
    .join("  ");

  return (
    <article
      data-testid="tool-card"
      data-call-id={record.call_id}
      data-status={record.status}
      data-tool={record.tool}
      className="rounded-xl border border-edge bg-panelAlt"
    >
      <header className="flex flex-wrap items-center gap-2 px-3 py-2">
        <span data-testid="tool-card-name" className="font-mono text-xs text-slate-100">
          {record.tool}
        </span>
        <StatusPill label={STATUS_LABEL[record.status]} tone={tone} testId="tool-card-status" />
        <RiskPill risk={record.risk} testId="tool-card-risk" />
        <span data-testid="tool-card-duration" className="text-[11px] text-slate-400">
          {formatDuration(record.duration_ms)}
        </span>
        <span className="text-[11px] text-slate-600">{formatTime(record.started_at)}</span>
        {record.error_code && (
          <span data-testid="tool-card-error" className="font-mono text-[11px] text-rose-300">
            {record.error_code}
          </span>
        )}
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="ml-auto rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent hover:text-slate-200"
        >
          {open ? "Hide" : "Details"}
        </button>
      </header>

      {preview !== "" && (
        <p
          data-testid="tool-card-params"
          className="truncate border-t border-edge px-3 py-1 font-mono text-[11px] text-slate-400"
          title={hasParams ? params : undefined}
        >
          {preview}
        </p>
      )}

      {record.summary !== "" && (
        <p
          data-testid="tool-card-summary"
          className={cn(
            "border-t border-edge px-3 py-2 text-xs",
            record.ok === false ? "text-rose-300" : "text-slate-300",
          )}
        >
          {record.summary}
        </p>
      )}

      {record.diff !== null && (
        <div className="border-t border-edge px-3 py-2">
          <DiffView diff={parseUnifiedDiff(record.diff)} title={record.tool + " diff"} />
        </div>
      )}

      {open && (
        <div className="border-t border-edge px-3 py-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Parameters</span>
            {hasParams && <CopyButton text={params} label="Copy JSON" />}
          </div>
          <pre className="scroll-thin mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#0b0e13] p-2 font-mono text-[11px] text-slate-300">
            {hasParams ? params : "no parameters"}
          </pre>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-400">
            <dt>call_id</dt>
            <dd className="truncate font-mono text-slate-300">{record.call_id}</dd>
            <dt>started</dt>
            <dd className="font-mono text-slate-300">{record.started_at || "—"}</dd>
            <dt>finished</dt>
            <dd className="font-mono text-slate-300">{record.finished_at ?? "—"}</dd>
          </dl>
        </div>
      )}
    </article>
  );
}
