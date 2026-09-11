import { useAppStore } from "../../store/useAppStore";
import { awaitingConfirmations } from "../../lib/events";
import { selectTimeline } from "../../store/useAppStore";
import { ConfirmationCard } from "./ConfirmationCard";

/**
 * The confirmation the console must answer: shown as a blocking dialog while a
 * run is waiting, with 拒绝 / 仅本次 / 本会话允许.
 */
export function ConfirmationDialog() {
  const timeline = useAppStore(selectTimeline);
  const respondConfirm = useAppStore((state) => state.respondConfirm);
  const pending = awaitingConfirmations(timeline);

  if (pending.length === 0) return null;

  return (
    <div
      data-testid="confirm-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="Confirmation required"
      className="absolute inset-x-0 bottom-0 z-20 border-t border-amber-900/70 bg-surface/95 p-3 backdrop-blur"
    >
      <div className="flex flex-col gap-2">
        {pending.map((entry) => (
          <ConfirmationCard key={entry.request_id} confirmation={entry} onChoose={respondConfirm} />
        ))}
      </div>
    </div>
  );
}
