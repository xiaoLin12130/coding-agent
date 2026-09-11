import type { ReactNode } from "react";

import { formatCount, formatRatio, formatRelative, asText } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, Field, SectionTitle, Spinner, StatusPill } from "../common/Ui";

function CountOrList({ items, mono = false }: { items: unknown[]; mono?: boolean }) {
  if (items.length === 0) return <span className="text-slate-500">none</span>;
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item, index) => (
        <li
          key={index}
          className={"truncate text-xs text-slate-300 " + (mono ? "font-mono" : "")}
          title={asText(item)}
        >
          {asText(item)}
        </li>
      ))}
    </ul>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="min-w-0 text-right text-slate-200">{children}</span>
    </div>
  );
}

/** Project State: the factual state the agent works from, plus recovery data. */
export function ProjectStateView() {
  const timeline = useAppStore(selectTimeline);
  const backend = useAppStore((state) => state.backend);
  const backendError = useAppStore((state) => state.backendError);
  const loadProjectState = useAppStore((state) => state.loadProjectState);
  const loadRecovery = useAppStore((state) => state.loadRecovery);
  const loadContext = useAppStore((state) => state.loadContext);
  const requestSnapshot = useAppStore((state) => state.requestSnapshot);
  const recovery = useAppStore((state) => state.recovery);
  const context = useAppStore((state) => state.context);
  const settings = useAppStore((state) => state.settings);
  const state = timeline.projectState;

  if (state === null) {
    return (
      <div className="flex flex-col gap-3" data-testid="project-state-empty">
        <BackendOffline detail={backendError} />
        {backend !== "offline" &&
          (timeline.running ? <Spinner label="Waiting for state_update…" /> : <Empty>No project state yet.</Empty>)}
        <button
          type="button"
          onClick={() => void loadProjectState()}
          className="self-start rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          Load project state
        </button>
      </div>
    );
  }

  const thresholds = settings.data?.context_thresholds ?? null;
  const pressure = recovery.data?.context_pressure ?? null;

  return (
    <div data-testid="project-state" className="flex flex-col gap-3">
      <BackendOffline detail={backendError} />

      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="refresh-state"
          onClick={() => void loadProjectState()}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          Refresh
        </button>
        <button
          type="button"
          data-testid="request-snapshot"
          onClick={requestSnapshot}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          Snapshot
        </button>
        <button
          type="button"
          data-testid="load-context"
          onClick={() => void loadContext(state.current_task ?? undefined)}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          Context
        </button>
      </div>

      <Field label="Milestone">
        <span data-testid="current-milestone">{asText(state.current_milestone)}</span>
      </Field>
      <Field label="Current task">
        <span data-testid="current-task">{asText(state.current_task)}</span>
      </Field>

      {state.goal && (
        <Field label="Goal">
          <p className="text-xs text-slate-300">{state.goal}</p>
        </Field>
      )}

      <Field label={"Todos (" + state.todos.length + ")"}>
        {state.todos.length === 0 ? (
          <span className="text-slate-500">none</span>
        ) : (
          <ul className="flex flex-col gap-1">
            {state.todos.map((todo, index) => (
              <li key={index} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate text-slate-300">{todo.content}</span>
                <StatusPill
                  label={todo.status}
                  tone={todo.status === "completed" ? "ok" : todo.status === "in_progress" ? "info" : "neutral"}
                />
              </li>
            ))}
          </ul>
        )}
      </Field>

      <Field label={"Files changed (" + state.files_changed.length + ")"}>
        <CountOrList items={state.files_changed} mono />
      </Field>
      <Field label="Tests">
        <CountOrList items={state.tests} />
      </Field>
      <Field label="Failures">
        <CountOrList items={state.failures} />
      </Field>
      <Field label="Decisions">
        <CountOrList items={state.decisions} />
      </Field>

      <Field label="Environment">
        <div className="flex flex-col gap-1">
          <Row label="git branch">{asText(state.git_branch)}</Row>
          <Row label="cwd">
            <span className="font-mono">{asText(state.cwd)}</span>
          </Row>
          <Row label="checkpoint">
            <span className="font-mono">{asText(state.checkpoint)}</span>
          </Row>
        </div>
      </Field>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle
          right={
            <button
              type="button"
              data-testid="refresh-recovery"
              onClick={() => void loadRecovery()}
              className="rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent"
            >
              Reload
            </button>
          }
        >
          Recovery
        </SectionTitle>

        {recovery.status === "error" && <Empty>{recovery.error}</Empty>}
        {recovery.data === null && recovery.status !== "error" && <Spinner label="Loading recovery…" />}

        {recovery.data && (
          <div className="flex flex-col gap-1" data-testid="recovery-panel">
            <Row label="session">{recovery.data.active_session_id ?? "—"}</Row>
            <Row label="messages">{formatCount(recovery.data.session_message_count)}</Row>
            <Row label="archived sessions">
              {formatCount(recovery.data.archived_session_ids.length)}
            </Row>
            <Row label="memory entries">{formatCount(recovery.data.memory_count)}</Row>
            <Row label="taken at">{formatRelative(recovery.data.taken_at)}</Row>

            {recovery.data.latest_run && (
              <div className="mt-1 rounded-lg border border-edge bg-surface p-2" data-testid="latest-run">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">Latest run</p>
                <Row label="run_id">{recovery.data.latest_run.run_id}</Row>
                <Row label="task">{recovery.data.latest_run.task || "—"}</Row>
                <Row label="step">{formatCount(recovery.data.latest_run.step)}</Row>
                <Row label="resumable">
                  <StatusPill
                    label={recovery.data.latest_run.resumable ? "yes" : "no"}
                    tone={recovery.data.latest_run.resumable ? "ok" : "warn"}
                  />
                </Row>
                {recovery.data.latest_run.reason && (
                  <p className="mt-1 text-[11px] text-slate-400">{recovery.data.latest_run.reason}</p>
                )}
              </div>
            )}

            {pressure && (
              <div className="mt-1 rounded-lg border border-edge bg-surface p-2" data-testid="context-pressure">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">Context pressure</p>
                <Row label="level">
                  <StatusPill
                    label={pressure.level}
                    tone={pressure.level === "hard" ? "bad" : pressure.level === "soft" ? "warn" : "ok"}
                    testId="pressure-level"
                  />
                </Row>
                <Row label="used">
                  {pressure.used_chars} / {pressure.budget_chars} chars
                </Row>
                <Row label="ratio">{formatRatio(pressure.ratio)}</Row>
                {pressure.dropped_sections.length > 0 && (
                  <Row label="dropped">{pressure.dropped_sections.join(", ")}</Row>
                )}
              </div>
            )}

            {thresholds && (
              <p className="mt-1 text-[11px] text-slate-500">
                thresholds: soft {formatRatio(thresholds.soft_ratio)} · hard{" "}
                {formatRatio(thresholds.hard_ratio)} · keep {thresholds.soft_recent_turns} recent turns
              </p>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Built context</SectionTitle>
        {context.data === null && context.status !== "error" && (
          <Empty>Press “Context” to ask the backend for the exact information it would send.</Empty>
        )}
        {context.status === "error" && <Empty>{context.error}</Empty>}
        {context.data && (
          <div className="flex flex-col gap-2" data-testid="context-panel">
            <p className="text-[11px] text-slate-500">
              {context.data.total_chars} / {context.data.budget_chars} chars ·{" "}
              {context.data.truncated ? "truncated" : "complete"} · {context.data.sections.length} sections
            </p>
            {context.data.dropped_sections.length > 0 && (
              <p className="text-[11px] text-amber-300">
                dropped: {context.data.dropped_sections.join(", ")}
              </p>
            )}
            <ul className="flex flex-col gap-1">
              {context.data.sections.map((section) => (
                <li key={section.name} className="rounded-lg border border-edge bg-surface p-2">
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="font-mono text-slate-200">{section.name}</span>
                    <span className="text-slate-500">
                      {section.included_chars}/{section.original_chars} chars
                      {section.truncated ? " · truncated" : ""}
                    </span>
                  </div>
                  {section.note && <p className="mt-1 text-[11px] text-slate-400">{section.note}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
