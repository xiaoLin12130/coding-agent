import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { eventLabel } from "../../lib/events";
import { basename, formatDuration, formatTime } from "../../lib/format";
import { selectTimeline, useAppStore } from "../../store/useAppStore";
import { BackendOffline } from "../common/BackendOffline";
import { CopyButton } from "../chat/CodeBlock";
import { Empty, SectionTitle, Spinner, StatusPill } from "../common/Ui";

/** Observability: screenshots, DOM snapshots, tool history, event history, Replay. */
export function ObservabilityPanel() {
  const artifacts = useAppStore((state) => state.artifacts);
  const loadArtifacts = useAppStore((state) => state.loadArtifacts);
  const events = useAppStore((state) => state.events);
  const timeline = useAppStore(selectTimeline);
  const replay = useAppStore((state) => state.replay);
  const setReplayIndex = useAppStore((state) => state.setReplayIndex);
  const stepReplay = useAppStore((state) => state.stepReplay);
  const startReplay = useAppStore((state) => state.startReplay);
  const stopReplay = useAppStore((state) => state.stopReplay);
  const toggleReplayPlay = useAppStore((state) => state.toggleReplayPlay);
  const toolCalls = useAppStore((state) => state.live.toolCalls);

  const runs = artifacts.data?.runs ?? [];
  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  const [snapshotText, setSnapshotText] = useState<string | null>(null);
  const [snapshotPath, setSnapshotPath] = useState<string | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  const active = useMemo(
    () => runs.find((run) => run.run_dir === selectedDir) ?? runs[0] ?? null,
    [runs, selectedDir],
  );

  // Replay playback: advance one recorded event at a time.
  useEffect(() => {
    if (!replay.playing) return;
    const timer = window.setInterval(() => {
      const next = useAppStore.getState().replay.index + 1;
      if (next >= events.length) {
        useAppStore.getState().toggleReplayPlay();
        return;
      }
      setReplayIndex(next);
    }, 700);
    return () => window.clearInterval(timer);
  }, [replay.playing, events.length, setReplayIndex]);

  const openSnapshot = (path: string) => {
    setSnapshotPath(path);
    setSnapshotText(null);
    setSnapshotError(null);
    void api
      .artifactText(path)
      .then((text) => setSnapshotText(text))
      .catch((error: unknown) =>
        setSnapshotError(error instanceof Error ? error.message : "could not read the snapshot"),
      );
  };

  return (
    <div className="flex flex-col gap-3" data-testid="observability-panel">
      <BackendOffline detail={artifacts.error} />

      <section className="flex flex-col gap-2">
        <SectionTitle
          right={
            <button
              type="button"
              data-testid="refresh-artifacts"
              onClick={() => void loadArtifacts()}
              className="rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent"
            >
              Reload
            </button>
          }
        >
          Artifact runs ({runs.length})
        </SectionTitle>

        {artifacts.status === "loading" && runs.length === 0 && <Spinner label="Loading artifacts…" />}
        {artifacts.status === "error" && runs.length === 0 && <Empty>{artifacts.error}</Empty>}
        {artifacts.status !== "loading" && runs.length === 0 && (
          <Empty>No browser run has written artifacts yet.</Empty>
        )}

        <ul data-testid="artifact-runs" className="flex flex-col gap-1">
          {runs.map((run) => (
            <li key={run.run_dir}>
              <button
                type="button"
                data-testid="artifact-run"
                data-run-dir={run.run_dir}
                aria-pressed={active?.run_dir === run.run_dir}
                onClick={() => setSelectedDir(run.run_dir)}
                className={
                  "w-full rounded-lg border px-2 py-1.5 text-left text-[11px] " +
                  (active?.run_dir === run.run_dir
                    ? "border-accent/60 bg-panelAlt"
                    : "border-edge bg-panelAlt/40")
                }
              >
                <span className="block truncate font-mono text-slate-200">{basename(run.run_dir)}</span>
                <span className="block text-slate-500">
                  {run.screenshots.length} screenshot · {run.dom_snapshots.length} DOM ·{" "}
                  {run.logs.length} log
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {active && (
        <section className="flex flex-col gap-2">
          <SectionTitle>Screenshots ({active.screenshots.length})</SectionTitle>
          {active.screenshots.length === 0 ? (
            <Empty>No screenshot in this run.</Empty>
          ) : (
            <div data-testid="screenshot-list" className="grid grid-cols-2 gap-2">
              {active.screenshots.map((path) => (
                <figure key={path} className="overflow-hidden rounded-lg border border-edge bg-panelAlt">
                  <img
                    data-testid="artifact-screenshot"
                    src={api.artifactUrl(path)}
                    alt={basename(path)}
                    className="h-28 w-full object-cover"
                    loading="lazy"
                  />
                  <figcaption className="truncate px-2 py-1 text-[10px] text-slate-500">
                    {basename(path)}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}

          <SectionTitle>DOM snapshots ({active.dom_snapshots.length})</SectionTitle>
          {active.dom_snapshots.length === 0 ? (
            <Empty>No DOM snapshot in this run.</Empty>
          ) : (
            <ul data-testid="dom-snapshot-list" className="flex flex-col gap-1">
              {active.dom_snapshots.map((path) => (
                <li key={path} className="flex items-center gap-2">
                  <button
                    type="button"
                    data-testid="dom-snapshot"
                    data-path={path}
                    onClick={() => openSnapshot(path)}
                    className="min-w-0 flex-1 truncate rounded-lg border border-edge bg-panelAlt px-2 py-1 text-left text-[11px] text-slate-300 hover:border-accent"
                  >
                    {basename(path)}
                  </button>
                  {snapshotPath === path && snapshotText !== null && (
                    <CopyButton text={snapshotText} label="Copy DOM" />
                  )}
                </li>
              ))}
            </ul>
          )}

          {snapshotError && <Empty>{snapshotError}</Empty>}
          {snapshotText !== null && (
            <pre
              data-testid="dom-snapshot-text"
              className="scroll-thin max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#0b0e13] p-2 font-mono text-[10px] text-slate-300"
            >
              {snapshotText}
            </pre>
          )}

          <SectionTitle>Run logs ({active.logs.length})</SectionTitle>
          {active.logs.length === 0 ? (
            <Empty>No log file in this run.</Empty>
          ) : (
            <ul data-testid="artifact-logs" className="flex flex-col gap-1">
              {active.logs.map((path) => (
                <li key={path} className="truncate font-mono text-[11px] text-slate-400">
                  {basename(path)}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2">
        <SectionTitle>Tool history ({toolCalls.length})</SectionTitle>
        {toolCalls.length === 0 ? (
          <Empty>No tool call in this session.</Empty>
        ) : (
          <ul data-testid="tool-history" className="flex flex-col gap-1">
            {toolCalls.map((tool) => (
              <li
                key={tool.call_id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-edge bg-panelAlt px-2 py-1 text-[11px]"
              >
                <span className="font-mono text-slate-200">{tool.tool}</span>
                <StatusPill
                  label={tool.status}
                  tone={tool.status === "ok" ? "ok" : tool.status === "failed" ? "bad" : "info"}
                />
                <StatusPill label={"risk: " + tool.risk} tone="neutral" />
                <span className="text-slate-400">{formatDuration(tool.duration_ms)}</span>
                <span className="ml-auto shrink-0 text-slate-600">{formatTime(tool.started_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <SectionTitle>Event history ({events.length})</SectionTitle>
        {events.length === 0 ? (
          <Empty>No event has been received yet.</Empty>
        ) : (
          <ul data-testid="observed-events" className="flex flex-col gap-1">
            {[...events].reverse().map((entry) => (
              <li
                key={entry.seq}
                data-testid="observed-event"
                className="flex items-center gap-2 rounded-lg border border-edge bg-panelAlt/60 px-2 py-1 text-[11px]"
              >
                <span className="w-6 shrink-0 text-right font-mono text-slate-600">{entry.seq}</span>
                <span className="font-mono text-slate-300">{entry.event}</span>
                <span className="truncate text-slate-400">{eventLabel(entry)}</span>
                <span className="ml-auto shrink-0 text-slate-600">{formatTime(entry.timestamp)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        data-testid="replay-controls"
        className="flex flex-col gap-2 rounded-lg border border-edge bg-panelAlt p-3"
      >
        <SectionTitle
          right={
            <StatusPill
              label={replay.active ? "replaying #" + (replay.index + 1) : "live"}
              tone={replay.active ? "info" : "ok"}
              testId="replay-status"
            />
          }
        >
          Replay
        </SectionTitle>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="replay-reset"
            disabled={events.length === 0}
            onClick={() => startReplay()}
            className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent disabled:opacity-40"
          >
            Load recording
          </button>
          <button
            type="button"
            data-testid="replay-prev"
            disabled={events.length === 0}
            onClick={() => stepReplay(-1)}
            className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent disabled:opacity-40"
          >
            ◀ Prev
          </button>
          <button
            type="button"
            data-testid="replay-play"
            disabled={events.length === 0}
            onClick={toggleReplayPlay}
            className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent disabled:opacity-40"
          >
            {replay.playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            data-testid="replay-next"
            disabled={events.length === 0}
            onClick={() => stepReplay(1)}
            className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent disabled:opacity-40"
          >
            Next ▶
          </button>
          <button
            type="button"
            data-testid="replay-stop"
            disabled={!replay.active}
            onClick={stopReplay}
            className="rounded-lg border border-edge px-2 py-1 text-[11px] text-slate-300 hover:border-accent disabled:opacity-40"
          >
            Back to live
          </button>
        </div>

        <input
          type="range"
          data-testid="replay-range"
          min={-1}
          max={Math.max(-1, events.length - 1)}
          value={replay.index}
          disabled={events.length === 0}
          onChange={(event) => setReplayIndex(Number(event.target.value))}
          className="w-full accent-accent"
        />

        <p className="text-[11px] text-slate-500">
          {events.length === 0
            ? "Nothing recorded yet: events arrive while a run streams."
            : "Event " +
              (replay.active ? replay.index + 1 : events.length) +
              " of " +
              events.length +
              " — the chat, tool cards and project state re-render from the recording."}
        </p>
        {replay.active && (
          <p data-testid="replay-summary" className="text-[11px] text-slate-400">
            replayed messages {timeline.messages.length} · tool cards {timeline.toolCalls.length} ·
            status {timeline.runStatus}
          </p>
        )}
      </section>
    </div>
  );
}
