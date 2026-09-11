import { useMemo } from "react";

import type { Settings } from "../../api/schema";
import { useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { Empty, SectionTitle, Spinner, StatusPill } from "../common/Ui";

const DOCUMENTED_POLICIES = ["ask", "auto_once", "deny"] as const;

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
        {settings.status === "loading" ? <Spinner label="Loading settings…" /> : <Empty>No settings.</Empty>}
        <button
          type="button"
          onClick={() => void loadSettings()}
          className="self-start rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          Load settings
        </button>
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
          {saveStatus === "loading" ? "Saving…" : "Save settings"}
        </button>
        <button
          type="button"
          data-testid="settings-reload"
          onClick={() => void loadSettings()}
          className="rounded-lg border border-edge px-3 py-1 text-xs text-slate-300 hover:border-accent"
        >
          Reload
        </button>
        {dirty && <StatusPill label="unsaved changes" tone="warn" testId="settings-dirty" />}
        {saveStatus === "ready" && !dirty && (
          <StatusPill label="saved" tone="ok" testId="settings-saved" />
        )}
        {saveStatus === "error" && (
          <StatusPill label={saveError ?? "save failed"} tone="bad" testId="settings-error" />
        )}
      </div>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Provider</SectionTitle>
        <Labeled label="name">
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
        <Labeled label="url">
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
          verified
        </label>
        <Labeled label="notes">
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
            profiles: {(draft.provider.profiles ?? []).join(", ")}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Browser</SectionTitle>
        <Labeled label="profile dir">
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
        <Labeled label="artifacts dir">
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
          headless allowed: {String(draft.browser.headless_allowed)} — the browser runs headed by
          policy (docs/browser.md), so the backend pins this to false.
        </p>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Working directory</SectionTitle>
        <input
          data-testid="settings-working-dir"
          className={inputClass}
          value={draft.working_dir}
          onChange={(event) => update((current) => ({ ...current, working_dir: event.target.value }))}
        />
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Safety</SectionTitle>
        <Labeled label="project root">
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
        <Labeled label="extra roots" hint="one path per line">
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
          confirm high-risk operations
        </label>
        {(draft.safety.sensitive_names ?? []).length > 0 && (
          <p className="text-[10px] text-slate-500">
            sensitive names: {(draft.safety.sensitive_names ?? []).join(", ")}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Confirmation</SectionTitle>
        <Labeled label="policy">
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
                {policy}
              </option>
            ))}
          </select>
        </Labeled>
        <Labeled label="ttl seconds">
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
          ask = every high-risk call waits for the console; auto_once = the runtime auto-answers
          “once”; deny = always reject.
        </p>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3">
        <SectionTitle>Context thresholds</SectionTitle>
        <div className="grid grid-cols-3 gap-2">
          <Labeled label="soft ratio">
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
          <Labeled label="hard ratio">
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
          <Labeled label="recent turns">
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
        <SectionTitle>Multi-agent</SectionTitle>
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
          enabled
        </label>
        <div className="grid grid-cols-2 gap-2">
          <Labeled label="max rounds">
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
          <Labeled label="stall threshold">
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
                <span className="font-mono text-slate-200">{role.name}</span> · max {role.max_steps}{" "}
                steps · {role.purpose}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-slate-600">
          roles come from the runtime and are read-only here, exactly as the backend stores them.
        </p>
      </section>
    </form>
  );
}
