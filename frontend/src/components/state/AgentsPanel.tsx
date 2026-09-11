import { useState } from "react";

import { formatDuration, formatTime, statusLabel } from "../../lib/format";
import { useAppStore } from "../../store/useAppStore";
import type { RunMode } from "../../types/ui";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, SectionTitle, Spinner, StatusPill } from "../common/Ui";

/** Agents panel: roles, the running run, its history, and the run controls. */
export function AgentsPanel() {
  const agents = useAppStore((state) => state.agents);
  const loadAgents = useAppStore((state) => state.loadAgents);
  const startRun = useAppStore((state) => state.startRun);
  const stopRun = useAppStore((state) => state.stopRun);
  const runId = useAppStore((state) => state.runId);
  const live = useAppStore((state) => state.live);

  const [task, setTask] = useState("");
  const [mode, setMode] = useState<RunMode>("single");
  const [maxSteps, setMaxSteps] = useState("");
  const [maxRounds, setMaxRounds] = useState("");
  const [autoConfirm, setAutoConfirm] = useState(false);

  const roles = agents.data?.roles ?? [];
  const runs = agents.data?.runs ?? [];
  const running = agents.data?.running ?? null;

  const submit = () => {
    if (task.trim() === "") return;
    const request = {
      task,
      mode,
      ...(maxSteps.trim() !== "" ? { max_steps: Number(maxSteps) } : {}),
      ...(maxRounds.trim() !== "" ? { max_rounds: Number(maxRounds) } : {}),
      auto_confirm: autoConfirm,
    };
    void startRun(request).then((accepted) => {
      if (accepted) setTask("");
    });
  };

  return (
    <div className="flex flex-col gap-3" data-testid="agents-panel">
      <BackendOffline detail={agents.error} />

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle
          right={
            <button
              type="button"
              data-testid="refresh-agents"
              onClick={() => void loadAgents()}
              className="rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent"
            >
              重新加载</button>
          }
        >
          运行中</SectionTitle>

        {running ? (
          <div data-testid="running-run" className="flex flex-col gap-1 text-[11px]">
            <div className="flex items-center gap-2">
              <span className="font-mono text-slate-200">{running.run_id}</span>
              <StatusPill label={running.status} tone="info" testId="running-status" />
              <StatusPill label={running.mode || "single"} tone="neutral" />
              <button
                type="button"
                data-testid="agents-stop"
                onClick={() => void stopRun()}
                className="ml-auto rounded-lg border border-rose-800 bg-rose-950/40 px-2 py-0.5 text-rose-200"
              >
                停止</button>
            </div>
            <p className="truncate text-slate-400" title={running.task}>
              {running.task}
            </p>
            <p className="text-slate-500">
              {running.tool_calls} 次工具调用 · 轮次 {running.round_count} ·{" "}
              {formatDuration(running.duration_ms)}
            </p>
          </div>
        ) : (
          <Empty>
            当前没有运行中的任务
            {live.runId ? "（上一次运行 " + live.runId + "）" : ""}。
          </Empty>
        )}

        {runId && (
          <p className="text-[10px] text-slate-600">控制台运行 ID：{runId}</p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>启动运行</SectionTitle>
        <textarea
          data-testid="agents-task"
          aria-label="任务"
          rows={3}
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="交给智能体运行时的任务"
          className="scroll-thin w-full resize-y rounded-lg border border-edge bg-surface px-2 py-1.5 text-xs placeholder:text-slate-500 focus:border-accent focus:outline-none"
        />
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
          <select
            aria-label="模式"
            data-testid="agents-mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as RunMode)}
            className="rounded-lg border border-edge bg-surface px-2 py-1"
          >
            <option value="single">single</option>
            <option value="multi">multi</option>
          </select>
          <label className="flex items-center gap-1">
            最大步数<input
              data-testid="agents-max-steps"
              value={maxSteps}
              onChange={(event) => setMaxSteps(event.target.value)}
              inputMode="numeric"
              className="w-14 rounded border border-edge bg-surface px-1 py-0.5"
            />
          </label>
          <label className="flex items-center gap-1">
            最大轮数<input
              data-testid="agents-max-rounds"
              value={maxRounds}
              onChange={(event) => setMaxRounds(event.target.value)}
              inputMode="numeric"
              className="w-14 rounded border border-edge bg-surface px-1 py-0.5"
            />
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              data-testid="agents-auto-confirm"
              checked={autoConfirm}
              onChange={(event) => setAutoConfirm(event.target.checked)}
            />
            自动确认</label>
          <button
            type="button"
            data-testid="agents-start"
            disabled={task.trim() === ""}
            onClick={submit}
            className="ml-auto rounded-lg bg-accent px-3 py-1 text-[11px] font-medium text-white disabled:opacity-40"
          >
            运行</button>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <SectionTitle>角色（{roles.length}）</SectionTitle>
        {agents.status === "loading" && roles.length === 0 && <Spinner label="正在加载角色…" />}
        {roles.length === 0 && agents.status !== "loading" ? (
          <Empty>没有角色信息。</Empty>
        ) : (
          <ul data-testid="role-list" className="flex flex-col gap-1">
            {roles.map((role) => (
              <li key={role.name} className="rounded-lg border border-edge bg-panelAlt px-2 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-100">{role.name}</span>
                  {role.verdict_kind && role.verdict_kind !== "none" && (
                    <StatusPill label={role.verdict_kind} tone="info" />
                  )}
                  <span className="ml-auto text-[10px] text-slate-500">最多 {role.max_steps} 步</span>
                </div>
                <p className="mt-1 text-[11px] text-slate-400">{role.purpose}</p>
                {role.allowed_tools.length > 0 && (
                  <p className="mt-1 truncate font-mono text-[10px] text-slate-500">
                    {role.allowed_tools.join(", ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <SectionTitle>运行历史（{runs.length}）</SectionTitle>
        {runs.length === 0 ? (
          <Empty>还没有运行记录。</Empty>
        ) : (
          <ul data-testid="run-history" className="flex flex-col gap-1">
            {runs.map((entry) => (
              <li
                key={entry.run_id + (entry.started_at ?? "")}
                data-testid="run-entry"
                className="flex flex-wrap items-center gap-2 rounded-lg border border-edge bg-panelAlt px-2 py-1 text-[11px]"
              >
                <span className="font-mono text-slate-200">{entry.run_id}</span>
                <StatusPill
                  label={statusLabel(entry.status)}
                  tone={entry.status === "completed" ? "ok" : entry.status === "failed" ? "bad" : "neutral"}
                />
                <span className="truncate text-slate-400" title={entry.task}>
                  {entry.task}
                </span>
                <span className="ml-auto shrink-0 text-slate-500">
                  {entry.tool_calls} tools · {formatDuration(entry.duration_ms)} ·{" "}
                  {formatTime(entry.started_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
