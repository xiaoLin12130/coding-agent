import { diffLines } from "diff";
import { useMemo } from "react";

import { cn } from "../../lib/format";

export type DiffLine = {
  kind: "add" | "del" | "ctx";
  text: string;
  oldLine: number | null;
  newLine: number | null;
};

/** Line diff between two texts, with line numbers on both sides. */
export function computeDiff(before: string, after: string): DiffLine[] {
  const parts = diffLines(before ?? "", after ?? "");
  const lines: DiffLine[] = [];
  let oldLine = 1;
  let newLine = 1;

  for (const part of parts) {
    const chunk = part.value.replace(/\n$/, "").split("\n");
    if (part.value === "") continue;
    for (const text of chunk) {
      if (part.added) {
        lines.push({ kind: "add", text, oldLine: null, newLine: newLine++ });
      } else if (part.removed) {
        lines.push({ kind: "del", text, oldLine: oldLine++, newLine: null });
      } else {
        lines.push({ kind: "ctx", text, oldLine: oldLine++, newLine: newLine++ });
      }
    }
  }
  return lines;
}

/** Read an already-unified diff (---/+++/@@) coming from a tool payload. */
export function parseUnifiedDiff(text: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  for (const raw of text.replace(/\n$/, "").split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      continue;
    }
    if (raw.startsWith("+++") || raw.startsWith("---")) continue;
    if (raw.startsWith("+")) {
      lines.push({ kind: "add", text: raw.slice(1), oldLine: null, newLine: newLine++ });
    } else if (raw.startsWith("-")) {
      lines.push({ kind: "del", text: raw.slice(1), oldLine: oldLine++, newLine: null });
    } else {
      lines.push({ kind: "ctx", text: raw.replace(/^ /, ""), oldLine: oldLine++, newLine: newLine++ });
    }
  }
  return lines;
}

const TONE: Record<DiffLine["kind"], string> = {
  add: "bg-emerald-950/40 text-emerald-200",
  del: "bg-rose-950/40 text-rose-200",
  ctx: "text-slate-300",
};

const MARK: Record<DiffLine["kind"], string> = { add: "+", del: "-", ctx: " " };

export function DiffView({
  diff,
  before,
  after,
  title,
}: {
  diff?: DiffLine[];
  before?: string;
  after?: string;
  title?: string;
}) {
  const lines = useMemo(() => {
    if (diff) return diff;
    if (before !== undefined && after !== undefined) return computeDiff(before, after);
    return [];
  }, [diff, before, after]);

  const added = lines.filter((line) => line.kind === "add").length;
  const removed = lines.filter((line) => line.kind === "del").length;

  return (
    <div data-testid="diff-view" className="overflow-hidden rounded-xl border border-edge bg-[#0b0e13]">
      <div className="flex items-center justify-between gap-2 border-b border-edge bg-panel px-3 py-1 text-[11px] text-slate-400">
        <span className="truncate">{title ?? "diff"}</span>
        <span className="shrink-0 font-mono">
          <span className="text-emerald-400">+{added}</span>{" "}
          <span className="text-rose-400">-{removed}</span>
        </span>
      </div>
      <div className="scroll-thin max-h-96 overflow-auto font-mono text-[12px] leading-5">
        {lines.length === 0 ? (
          <p className="px-3 py-2 text-slate-500">没有可显示的改动。</p>
        ) : (
          lines.map((line, index) => (
            <div key={index} className={cn("flex gap-2 px-2", TONE[line.kind])}>
              <span className="w-8 shrink-0 select-none text-right text-slate-600">
                {line.oldLine ?? ""}
              </span>
              <span className="w-8 shrink-0 select-none text-right text-slate-600">
                {line.newLine ?? ""}
              </span>
              <span className="w-3 shrink-0 select-none text-slate-500">{MARK[line.kind]}</span>
              <span className="whitespace-pre-wrap break-words">{line.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
