import type { ReactNode } from "react";

import { cn } from "../../lib/format";

export function StatusPill({
  label,
  tone = "neutral",
  testId,
}: {
  label: string;
  tone?: "neutral" | "ok" | "warn" | "bad" | "info";
  testId?: string;
}) {
  const tones: Record<string, string> = {
    neutral: "border-edge bg-panelAlt text-slate-400",
    ok: "border-emerald-900 bg-emerald-950/30 text-emerald-300",
    warn: "border-amber-900 bg-amber-950/30 text-amber-300",
    bad: "border-rose-900 bg-rose-950/40 text-rose-300",
    info: "border-sky-900 bg-sky-950/30 text-sky-300",
  };
  return (
    <span
      data-testid={testId}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] leading-4",
        tones[tone],
      )}
    >
      {label}
    </span>
  );
}

export function RiskPill({ risk, testId }: { risk: string; testId?: string }) {
  const value = (risk || "unknown").toLowerCase();
  const tone = value === "high" || value === "critical" ? "bad" : value === "medium" ? "warn" : value === "low" ? "ok" : "neutral";
  return <StatusPill label={"risk: " + (risk || "unknown")} tone={tone} testId={testId} />;
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{children}</h3>
      {right}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-edge bg-panelAlt p-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <div className="mt-1 text-sm text-slate-200">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-xs text-slate-500">{children}</p>;
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-400">
      <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
      {label}
    </span>
  );
}
