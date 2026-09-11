import type { ReactNode } from "react";

import type { ProjectState, StateStatus } from "../types";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-edge bg-panelAlt p-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <div className="mt-1 text-sm text-slate-200">{children}</div>
    </div>
  );
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[unreadable value]";
  }
}

function CountOrList({ items }: { items: unknown[] }) {
  if (items.length === 0) return <span className="text-slate-500">none</span>;
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item, index) => (
        <li key={index} className="truncate text-xs text-slate-300">
          {asText(item)}
        </li>
      ))}
    </ul>
  );
}

export function ProjectStateView({
  state,
  status,
  error,
  memoryCount,
}: {
  state: ProjectState | null;
  status: StateStatus;
  error: string | null;
  memoryCount: number | null;
}) {
  if (status === "error") {
    return (
      <div
        data-testid="project-state-offline"
        className="rounded-lg border border-rose-900/60 bg-rose-950/30 p-3 text-sm text-rose-300"
      >
        <p className="font-medium">Backend offline</p>
        <p className="mt-1 text-xs">{error ?? "Could not read project state."}</p>
      </div>
    );
  }

  if (state === null) {
    return (
      <p data-testid="project-state-loading" className="text-sm text-slate-500">
        {status === "loading" ? "Loading project state…" : "No project state."}
      </p>
    );
  }

  return (
    <div data-testid="project-state" className="flex flex-col gap-3">
      <Field label="Current milestone">
        <span data-testid="current-milestone">{asText(state.current_milestone)}</span>
      </Field>
      <Field label="Current task">
        <span data-testid="current-task">{asText(state.current_task)}</span>
      </Field>
      <Field label="Todos">
        {state.todos.length === 0 ? (
          <span className="text-slate-500">none</span>
        ) : (
          <ul className="flex flex-col gap-1">
            {state.todos.map((todo, index) => (
              <li key={index} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate text-slate-300">{todo.content}</span>
                <span className="text-slate-500">{todo.status}</span>
              </li>
            ))}
          </ul>
        )}
      </Field>
      <Field label="Files changed">
        <CountOrList items={state.files_changed} />
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
      <Field label="Checkpoint">
        <span className="text-xs">{asText(state.checkpoint)}</span>
      </Field>
      <Field label="Memory entries">
        <span className="text-xs">
          {memoryCount === null ? "—" : String(memoryCount)}
        </span>
      </Field>
    </div>
  );
}
