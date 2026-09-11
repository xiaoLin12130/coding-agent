import type { ReactNode } from "react";

import { formatCount, formatRatio, formatRelative, asText } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, Field, SectionTitle, Spinner, StatusPill } from "../common/Ui";

function CountOrList({ items, mono = false }: { items: unknown[]; mono?: boolean }) {
  if (items.length === 0) return <span className="text-slate-500">无</span>;
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
          (timeline.running ? <Spinner label="等待 state_update…" /> : <Empty>还没有项目状态。</Empty>)}
        <button
          type="button"
          onClick={() => void loadProjectState()}
          className="self-start rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          载入项目状态</button>
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
          刷新</button>
        <button
          type="button"
          data-testid="request-snapshot"
          onClick={requestSnapshot}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          快照</button>
        <button
          type="button"
          data-testid="load-context"
          onClick={() => void loadContext(state.current_task ?? undefined)}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          上下文</button>
      </div>

      <Field label="里程碑">
        <span data-testid="current-milestone">{asText(state.current_milestone)}</span>
      </Field>
      <Field label="当前任务">
        <span data-testid="current-task">{asText(state.current_task)}</span>
      </Field>

      {state.goal && (
        <Field label="目标">
          <p className="text-xs text-slate-300">{state.goal}</p>
        </Field>
      )}

      <Field label={"待办（" + state.todos.length + "）"}>
        {state.todos.length === 0 ? (
          <span className="text-slate-500">无</span>
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

      <Field label={"改动的文件（" + state.files_changed.length + "）"}>
        <CountOrList items={state.files_changed} mono />
      </Field>
      <Field label="测试">
        <CountOrList items={state.tests} />
      </Field>
      <Field label="失败">
        <CountOrList items={state.failures} />
      </Field>
      <Field label="决策">
        <CountOrList items={state.decisions} />
      </Field>

      <Field label="环境">
        <div className="flex flex-col gap-1">
          <Row label="git 分支">{asText(state.git_branch)}</Row>
          <Row label="工作目录">
            <span className="font-mono">{asText(state.cwd)}</span>
          </Row>
          <Row label="检查点">
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
              重新加载</button>
          }
        >
          恢复</SectionTitle>

        {recovery.status === "error" && <Empty>{recovery.error}</Empty>}
        {recovery.data === null && recovery.status !== "error" && <Spinner label="正在加载恢复信息…" />}

        {recovery.data && (
          <div className="flex flex-col gap-1" data-testid="recovery-panel">
            <Row label="会话">{recovery.data.active_session_id ?? "—"}</Row>
            <Row label="消息数">{formatCount(recovery.data.session_message_count)}</Row>
            <Row label="已归档会话">
              {formatCount(recovery.data.archived_session_ids.length)}
            </Row>
            <Row label="记忆条目">{formatCount(recovery.data.memory_count)}</Row>
            <Row label="快照时间">{formatRelative(recovery.data.taken_at)}</Row>

            {recovery.data.latest_run && (
              <div className="mt-1 rounded-lg border border-edge bg-surface p-2" data-testid="latest-run">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">最近一次运行</p>
                <Row label="运行 ID">{recovery.data.latest_run.run_id}</Row>
                <Row label="任务">{recovery.data.latest_run.task || "—"}</Row>
                <Row label="步数">{formatCount(recovery.data.latest_run.step)}</Row>
                <Row label="可恢复">
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
                <p className="text-[11px] uppercase tracking-wide text-slate-500">上下文压力</p>
                <Row label="级别">
                  <StatusPill
                    label={pressure.level}
                    tone={pressure.level === "hard" ? "bad" : pressure.level === "soft" ? "warn" : "ok"}
                    testId="pressure-level"
                  />
                </Row>
                <Row label="已用">
                  {pressure.used_chars} / {pressure.budget_chars} chars
                </Row>
                <Row label="占比">{formatRatio(pressure.ratio)}</Row>
                {pressure.dropped_sections.length > 0 && (
                  <Row label="已丢弃">{pressure.dropped_sections.join(", ")}</Row>
                )}
              </div>
            )}

            {thresholds && (
              <p className="mt-1 text-[11px] text-slate-500">
                阈值：软 {formatRatio(thresholds.soft_ratio)} · 硬{" "}
                {formatRatio(thresholds.hard_ratio)} · 保留最近 {thresholds.soft_recent_turns} 轮
              </p>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>构建后的上下文</SectionTitle>
        {context.data === null && context.status !== "error" && (
          <Empty>点击“上下文”，向后端请求它实际会发送的完整信息。</Empty>
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
