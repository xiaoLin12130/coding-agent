import { useMemo } from "react";

import type { Settings } from "../../api/schema";
import { useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, SectionTitle, Spinner, StatusPill } from "../common/Ui";

const DOCUMENTED_POLICIES = ["ask", "auto_once", "deny"] as const;

/** The wire values stay English; the select shows what they mean. */
const POLICY_LABELS: Record<string, string> = {
  ask: "每次都询问",
  auto_once: "自动允许一次",
  deny: "一律拒绝",
};

function Labeled({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wide text-slate-500">{label}</span>
      {children}
      {hint && <span className="text-[10px] text-slate-600">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-edge bg-surface px-2 py-1.5 font-mono text-xs text-slate-100 placeholder:text-slate-600 focus:border-accent focus:outline-none";

/** Settings: provider, browser, working dir, safety, confirmation, thresholds, multi-agent. */
export function SettingsPanel() {
  const settings = useAppStore((state) => state.settings);
  const draft = useAppStore((state) => state.settingsDraft);
  const setDraft = useAppStore((state) => state.setSettingsDraft);
  const save = useAppStore((state) => state.saveSettings);
  const loadSettings = useAppStore((state) => state.loadSettings);
  const saveStatus = useAppStore((state) => state.saveStatus);
  const saveError = useAppStore((state) => state.saveError);

  const dirty = useMemo(
    () => draft !== null && settings.data !== null && JSON.stringify(draft) !== JSON.stringify(settings.data),
    [draft, settings.data],
  );

  if (draft === null) {
    return (
      <div className="flex flex-col gap-3" data-testid="settings-panel">
        <BackendOffline detail={settings.error} />
        {settings.status === "loading" ? <Spinner label="正在加载设置…" /> : <Empty>暂无设置。</Empty>}
        <button
          type="button"
          onClick={() => void loadSettings()}
          className="self-start rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          载入设置</button>
      </div>
    );
  }

  const update = (updater: (current: Settings) => Settings) => {
    setDraft(updater(draft));
  };

  const policyOptions = Array.from(
    new Set<string>([...DOCUMENTED_POLICIES, draft.confirmation.policy]),
  );

  return (
    <form
      data-testid="settings-panel"
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <BackendOffline detail={settings.error} />

      <div className="flex items-center gap-2">
        <button
          type="submit"
          data-testid="settings-save"
          className="rounded-lg bg-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
          disabled={saveStatus === "loading"}
        >
          {saveStatus === "loading" ? "保存中…" : "保存设置"}
        </button>
        <button
          type="button"
          data-testid="settings-reload"
          onClick={() => void loadSettings()}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          重新加载</button>
        {dirty && <StatusPill label="有未保存的修改" tone="warn" testId="settings-dirty" />}
        {saveStatus === "ready" && !dirty && (
          <StatusPill label="已保存" tone="ok" testId="settings-saved" />
        )}
        {saveStatus === "error" && (
          <StatusPill label={saveError ?? "save failed"} tone="bad" testId="settings-error" />
        )}
      </div>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>模型提供方</SectionTitle>
        <Labeled label="名称">
          <input
            data-testid="settings-provider-name"
            className={inputClass}
            value={draft.provider.name}
            onChange={(event) =>
              update((current) => ({
                ...current,
                provider: { ...current.provider, name: event.target.value },
              }))
            }
          />
        </Labeled>
        <Labeled label="地址">
          <input
            data-testid="settings-provider-url"
            className={inputClass}
            value={draft.provider.url}
            onChange={(event) =>
              update((current) => ({
                ...current,
                provider: { ...current.provider, url: event.target.value },
              }))
            }
          />
        </Labeled>
        <label className="flex items-center gap-2 text-[11px] text-slate-400">
          <input
            type="checkbox"
            data-testid="settings-provider-verified"
            checked={draft.provider.verified}
            onChange={(event) =>
              update((current) => ({
                ...current,
                provider: { ...current.provider, verified: event.target.checked },
              }))
            }
          />
          已验证
        </label>
        <Labeled label="说明">
          <textarea
            data-testid="settings-provider-notes"
            rows={2}
            className={inputClass}
            value={draft.provider.notes}
            onChange={(event) =>
              update((current) => ({
                ...current,
                provider: { ...current.provider, notes: event.target.value },
              }))
            }
          />
        </Labeled>
        {(draft.provider.profiles ?? []).length > 0 && (
          <p className="text-[10px] text-slate-500">
            可用配置：{(draft.provider.profiles ?? []).join(", ")}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>浏览器</SectionTitle>
        <Labeled label="浏览器资料目录">
          <input
            data-testid="settings-browser-profile"
            className={inputClass}
            value={draft.browser.profile_dir}
            onChange={(event) =>
              update((current) => ({
                ...current,
                browser: { ...current.browser, profile_dir: event.target.value },
              }))
            }
          />
        </Labeled>
        <Labeled label="工件目录">
          <input
            data-testid="settings-browser-artifacts"
            className={inputClass}
            value={draft.browser.artifacts_dir}
            onChange={(event) =>
              update((current) => ({
                ...current,
                browser: { ...current.browser, artifacts_dir: event.target.value },
              }))
            }
          />
        </Labeled>
        <p className="text-[10px] text-slate-500">
          允许无头模式：{String(draft.browser.headless_allowed)} —— 按策略（docs/browser.md）浏览器必须是有界面的，
          因此后端固定为 false。
        </p>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>工作目录</SectionTitle>
        <input
          data-testid="settings-working-dir"
          className={inputClass}
          value={draft.working_dir}
          onChange={(event) => update((current) => ({ ...current, working_dir: event.target.value }))}
        />
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>安全</SectionTitle>
        <Labeled label="项目根目录">
          <input
            data-testid="settings-safety-root"
            className={inputClass}
            value={draft.safety.project_root}
            onChange={(event) =>
              update((current) => ({
                ...current,
                safety: { ...current.safety, project_root: event.target.value },
              }))
            }
          />
        </Labeled>
        <Labeled label="额外允许的目录" hint="每行一个路径">
          <textarea
            data-testid="settings-safety-extra-roots"
            rows={2}
            className={inputClass}
            value={draft.safety.extra_roots.join("\n")}
            onChange={(event) =>
              update((current) => ({
                ...current,
                safety: {
                  ...current.safety,
                  extra_roots: event.target.value.split("\n").filter((line) => line.trim() !== ""),
                },
              }))
            }
          />
        </Labeled>
        <label className="flex items-center gap-2 text-[11px] text-slate-400">
          <input
            type="checkbox"
            data-testid="settings-safety-confirm"
            checked={draft.safety.confirm_high_risk}
            onChange={(event) =>
              update((current) => ({
                ...current,
                safety: { ...current.safety, confirm_high_risk: event.target.checked },
              }))
            }
          />
          高风险操作需要确认
        </label>
        {(draft.safety.sensitive_names ?? []).length > 0 && (
          <p className="text-[10px] text-slate-500">
            敏感文件名：{(draft.safety.sensitive_names ?? []).join(", ")}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>确认策略</SectionTitle>
        <Labeled label="策略">
          <select
            data-testid="settings-policy"
            className={inputClass}
            value={draft.confirmation.policy}
            onChange={(event) =>
              update((current) => ({
                ...current,
                confirmation: { ...current.confirmation, policy: event.target.value as Settings["confirmation"]["policy"] },
              }))
            }
          >
            {policyOptions.map((policy) => (
              <option key={policy} value={policy}>
                {POLICY_LABELS[policy] ?? policy}
              </option>
            ))}
          </select>
        </Labeled>
        <Labeled label="确认超时（秒）">
          <input
            type="number"
            data-testid="settings-ttl"
            className={inputClass}
            value={draft.confirmation.ttl_seconds}
            onChange={(event) =>
              update((current) => ({
                ...current,
                confirmation: { ...current.confirmation, ttl_seconds: Number(event.target.value) },
              }))
            }
          />
        </Labeled>
        <p className="text-[10px] text-slate-600">
          ask = 每个高风险调用都等待控制台确认；auto_once = 运行时自动回答“仅一次”；deny = 一律拒绝。
        </p>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>上下文阈值</SectionTitle>
        <div className="grid grid-cols-3 gap-2">
          <Labeled label="软阈值比例">
            <input
              type="number"
              step="0.05"
              data-testid="settings-soft-ratio"
              className={inputClass}
              value={draft.context_thresholds.soft_ratio}
              onChange={(event) =>
                update((current) => ({
                  ...current,
                  context_thresholds: {
                    ...current.context_thresholds,
                    soft_ratio: Number(event.target.value),
                  },
                }))
              }
            />
          </Labeled>
          <Labeled label="硬阈值比例">
            <input
              type="number"
              step="0.05"
              data-testid="settings-hard-ratio"
              className={inputClass}
              value={draft.context_thresholds.hard_ratio}
              onChange={(event) =>
                update((current) => ({
                  ...current,
                  context_thresholds: {
                    ...current.context_thresholds,
                    hard_ratio: Number(event.target.value),
                  },
                }))
              }
            />
          </Labeled>
          <Labeled label="保留最近轮数">
            <input
              type="number"
              data-testid="settings-soft-turns"
              className={inputClass}
              value={draft.context_thresholds.soft_recent_turns}
              onChange={(event) =>
                update((current) => ({
                  ...current,
                  context_thresholds: {
                    ...current.context_thresholds,
                    soft_recent_turns: Number(event.target.value),
                  },
                }))
              }
            />
          </Labeled>
        </div>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>多智能体</SectionTitle>
        <label className="flex items-center gap-2 text-[11px] text-slate-400">
          <input
            type="checkbox"
            data-testid="settings-multi-enabled"
            checked={draft.multi_agent.enabled}
            onChange={(event) =>
              update((current) => ({
                ...current,
                multi_agent: { ...current.multi_agent, enabled: event.target.checked },
              }))
            }
          />
          启用
        </label>
        <div className="grid grid-cols-2 gap-2">
          <Labeled label="最大轮数">
            <input
              type="number"
              data-testid="settings-multi-rounds"
              className={inputClass}
              value={draft.multi_agent.max_rounds}
              onChange={(event) =>
                update((current) => ({
                  ...current,
                  multi_agent: { ...current.multi_agent, max_rounds: Number(event.target.value) },
                }))
              }
            />
          </Labeled>
          <Labeled label="停滞阈值">
            <input
              type="number"
              data-testid="settings-multi-stall"
              className={inputClass}
              value={draft.multi_agent.stall_threshold}
              onChange={(event) =>
                update((current) => ({
                  ...current,
                  multi_agent: {
                    ...current.multi_agent,
                    stall_threshold: Number(event.target.value),
                  },
                }))
              }
            />
          </Labeled>
        </div>
        {draft.multi_agent.roles.length > 0 && (
          <ul data-testid="settings-roles" className="flex flex-col gap-1">
            {draft.multi_agent.roles.map((role) => (
              <li key={role.name} className="text-[11px] text-slate-400">
                <span className="font-mono text-slate-200">{role.name}</span> · 最多 {role.max_steps}{" "}
                步 · {role.purpose}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-slate-600">
          角色来自运行时，这里只读显示，与后端存储完全一致。
        </p>
      </section>
    </form>
  );
}
