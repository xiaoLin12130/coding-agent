import { cn } from "../../lib/format";
import type { ConfirmChoice, PendingConfirmation } from "../../types/ui";
import { CopyButton } from "../chat/CodeBlock";
import { RiskPill } from "../common/Ui";

/** The three answers the frozen contract accepts. */
export const CONFIRM_CHOICES: Array<{ choice: ConfirmChoice; label: string; hint: string; tone: string }> = [
  {
    choice: "reject",
    label: "拒绝",
    hint: "Reject this call (the agent is told it was refused).",
    tone: "border-rose-800 bg-rose-950/40 text-rose-200 hover:bg-rose-900/40",
  },
  {
    choice: "once",
    label: "仅本次",
    hint: "Allow this call only, this time.",
    tone: "border-amber-800 bg-amber-950/40 text-amber-200 hover:bg-amber-900/40",
  },
  {
    choice: "session",
    label: "本会话允许",
    hint: "Allow this tool for the rest of the session.",
    tone: "border-emerald-800 bg-emerald-950/40 text-emerald-200 hover:bg-emerald-900/40",
  },
];

export function ConfirmationCard({
  confirmation,
  onChoose,
  compact = false,
}: {
  confirmation: PendingConfirmation;
  onChoose: (requestId: string, choice: ConfirmChoice) => void;
  compact?: boolean;
}) {
  const answered = confirmation.answered_with;
  const params = confirmation.args ? JSON.stringify(confirmation.args, null, 2) : "";

  return (
    <article
      data-testid="confirm-card"
      data-request-id={confirmation.request_id}
      data-answered={answered ?? "no"}
      className={cn(
        "rounded-xl border bg-panelAlt",
        answered ? "border-edge opacity-70" : "border-amber-900/70",
      )}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
        <span className="text-xs font-semibold text-amber-200">Confirmation required</span>
        <span data-testid="confirm-tool" className="font-mono text-xs text-slate-100">
          {confirmation.tool}
        </span>
        <RiskPill risk={confirmation.risk} testId="confirm-risk" />
        {answered && (
          <span data-testid="confirm-answered" className="text-[11px] text-slate-400">
            answered: {answered}
          </span>
        )}
      </header>

      <div className={cn("flex flex-col gap-3 px-3 py-3", compact && "text-xs")}>
        {confirmation.command !== "" && (
          <div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Command</span>
              <CopyButton text={confirmation.command} />
            </div>
            <pre
              data-testid="confirm-command"
              className="scroll-thin mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#0b0e13] p-2 font-mono text-[11px] text-slate-200"
            >
              {confirmation.command}
            </pre>
          </div>
        )}

        {confirmation.command === "" && params !== "" && (
          <div>
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Parameters</span>
            <pre
              data-testid="confirm-params"
              className="scroll-thin mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#0b0e13] p-2 font-mono text-[11px] text-slate-200"
            >
              {params}
            </pre>
          </div>
        )}

        {confirmation.cwd !== "" && (
          <p className="text-[11px] text-slate-400">
            cwd: <span data-testid="confirm-cwd" className="font-mono text-slate-300">{confirmation.cwd}</span>
          </p>
        )}

        {confirmation.impact.length > 0 && (
          <div>
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Impact</span>
            <ul data-testid="confirm-impact" className="mt-1 list-disc pl-5 text-xs text-slate-300">
              {confirmation.impact.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {confirmation.reasons.length > 0 && (
          <div>
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Reasons</span>
            <ul data-testid="confirm-reasons" className="mt-1 list-disc pl-5 text-xs text-slate-400">
              {confirmation.reasons.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {CONFIRM_CHOICES.map((entry) => {
            const unavailable =
              confirmation.choices.length > 0 && !confirmation.choices.includes(entry.choice);
            return (
              <button
                key={entry.choice}
                type="button"
                title={entry.hint}
                data-testid={"confirm-" + entry.choice}
                data-choice={entry.choice}
                disabled={answered !== null || unavailable}
                onClick={() => onChoose(confirmation.request_id, entry.choice)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40",
                  entry.tone,
                )}
              >
                {entry.label}
              </button>
            );
          })}
        </div>
      </div>
    </article>
  );
}
