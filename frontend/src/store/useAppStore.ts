/**
 * The console store (zustand).
 *
 * One store keeps: the socket, the live timeline folded from the event stream,
 * the recorded events (for history + Replay), every REST resource the panels
 * read, and the backend-reachability flag that drives the "backend offline"
 * state.
 */

import { create } from "zustand";

import { api, errorMessage, isOfflineError } from "../api/client";
import type {
  AgentsResponse,
  ArtifactsResponse,
  BuiltContext,
  LogsResponse,
  MemoryEntry,
  RecoverySnapshot,
  SessionInfo,
  Settings,
  TranscriptEntry,
} from "../api/schema";
import {
  applyFrame,
  emptyTimeline,
  foldEvents,
  type ToolCallFields,
} from "../lib/events";
import { createChatClient, type ChatClient, type ChatClientFrame, type ParsedFrame } from "../lib/ws";
import type {
  AgentEventName,
  BackendStatus,
  ConnectionStatus,
  ConfirmChoice,
  EventRecord,
  LoadStatus,
  RunRequest,
  TimelineMessage,
  TimelineState,
} from "../types/ui";

export type Resource<T> = {
  data: T | null;
  status: LoadStatus;
  error: string | null;
};

function resource<T>(): Resource<T> {
  return { data: null, status: "idle", error: null };
}

function newId(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Math.random().toString(16).slice(2);
  return prefix + "-" + random;
}

function nowIso(): string {
  return new Date().toISOString();
}

const MAX_EVENTS = 500;

let client: ChatClient | null = null;
let wiredClient: ChatClient | null = null;

/** Inject a client (tests); pass null to fall back to the real socket. */
export function setChatClient(next: ChatClient | null): void {
  client = next;
  wiredClient = null;
}

export function getChatClient(): ChatClient {
  if (!client) client = createChatClient();
  return client;
}

export type ReplayState = {
  active: boolean;
  index: number;
  playing: boolean;
  view: TimelineState;
};

export type AppStore = {
  // availability -----------------------------------------------------------
  backend: BackendStatus;
  backendError: string | null;

  // socket -----------------------------------------------------------------
  connection: ConnectionStatus;
  notices: string[];

  // live data --------------------------------------------------------------
  live: TimelineState;
  events: EventRecord[];
  replay: ReplayState;

  // resources --------------------------------------------------------------
  sessions: Resource<SessionInfo[]>;
  activeSessionId: string | null;
  sessionQuery: string;
  sessionRecovered: boolean;
  memory: Resource<MemoryEntry[]>;
  logs: Resource<LogsResponse>;
  agents: Resource<AgentsResponse>;
  artifacts: Resource<ArtifactsResponse>;
  settings: Resource<Settings>;
  settingsDraft: Settings | null;
  saveStatus: LoadStatus;
  saveError: string | null;
  recovery: Resource<RecoverySnapshot>;
  context: Resource<BuiltContext>;

  // run --------------------------------------------------------------------
  runId: string | null;
  runMode: "single" | "multi";
  runTask: string;

  // actions ----------------------------------------------------------------
  bootstrap: () => Promise<void>;
  connect: () => void;
  reconnect: () => void;
  checkBackend: () => Promise<boolean>;
  pushNotice: (notice: string) => void;
  clearNotices: () => void;
  handleFrame: (frame: ParsedFrame) => void;

  sendChat: (content: string) => boolean;
  startRun: (request: RunRequest) => Promise<boolean>;
  stopRun: () => Promise<void>;
  requestSnapshot: () => void;
  respondConfirm: (requestId: string, choice: ConfirmChoice) => void;

  loadSessions: () => Promise<void>;
  newSession: (title?: string) => Promise<void>;
  switchSession: (sessionId: string) => Promise<void>;
  archiveSession: (sessionId: string) => Promise<void>;
  setSessionQuery: (query: string) => void;

  loadProjectState: () => Promise<void>;
  loadMemory: () => Promise<void>;
  loadLogs: () => Promise<void>;
  loadAgents: () => Promise<void>;
  loadArtifacts: () => Promise<void>;
  loadSettings: () => Promise<void>;
  loadRecovery: () => Promise<void>;
  loadContext: (task?: string) => Promise<void>;
  loadAll: () => Promise<void>;

  setSettingsDraft: (next: Settings) => void;
  saveSettings: (next?: Settings) => Promise<void>;

  startReplay: () => void;
  stopReplay: () => void;
  setReplayIndex: (index: number) => void;
  stepReplay: (delta: number) => void;
  toggleReplayPlay: () => void;
};

const initialState = {
  backend: "unknown" as BackendStatus,
  backendError: null as string | null,
  connection: "disconnected" as ConnectionStatus,
  notices: [] as string[],
  live: emptyTimeline(),
  events: [] as EventRecord[],
  replay: { active: false, index: -1, playing: false, view: emptyTimeline() } as ReplayState,
  sessions: resource<SessionInfo[]>(),
  activeSessionId: null as string | null,
  sessionQuery: "",
  sessionRecovered: false,
  memory: resource<MemoryEntry[]>(),
  logs: resource<LogsResponse>(),
  agents: resource<AgentsResponse>(),
  artifacts: resource<ArtifactsResponse>(),
  settings: resource<Settings>(),
  settingsDraft: null as Settings | null,
  saveStatus: "idle" as LoadStatus,
  saveError: null as string | null,
  recovery: resource<RecoverySnapshot>(),
  context: resource<BuiltContext>(),
  runId: null as string | null,
  runMode: "single" as "single" | "multi",
  runTask: "",
};

/** Local echo of an outgoing task, so the chat shows what was asked. */
function localMessage(content: string, role: TimelineMessage["role"], seq: number): TimelineMessage {
  return { id: newId(role), role, content, created_at: nowIso(), seq };
}

function transcriptToMessages(entries: TranscriptEntry[]): TimelineMessage[] {
  return entries.map((entry, position) => ({
    id: entry.session_id + "-" + entry.index + "-" + position,
    role: entry.role,
    content: entry.content,
    created_at: entry.created_at,
    seq: position + 1,
    tool_name: entry.tool_name ?? null,
    tool_call_id: entry.tool_call_id ?? null,
  }));
}

export const useAppStore = create<AppStore>((set, get) => {
  /** Record a failed resource load; a transport failure means "offline". */
  function fail(
    key: "memory" | "logs" | "agents" | "artifacts" | "settings" | "recovery" | "context",
    error: unknown,
  ): void {
    const message = errorMessage(error);
    const offline = isOfflineError(error);
    set((state) => {
      const next: Partial<AppStore> = {};
      next[key] = { ...(state[key] as Resource<unknown>), status: "error", error: message } as never;
      if (offline) {
        next.backend = "offline";
        next.backendError = message;
      }
      return next;
    });
  }

  function loading(
    key: "memory" | "logs" | "agents" | "artifacts" | "settings" | "recovery" | "context",
  ): void {
    set((state) => {
      const next: Partial<AppStore> = {};
      next[key] = { ...(state[key] as Resource<unknown>), status: "loading", error: null } as never;
      return next;
    });
  }

  return {
    ...initialState,

    async bootstrap() {
      get().connect();
      await get().checkBackend();
      await get().loadSessions();
      // Restore the active session's transcript before anything else streams.
      const activeSessionId = get().activeSessionId;
      if (activeSessionId) await get().switchSession(activeSessionId);
      await Promise.all([
        get().loadProjectState(),
        get().loadMemory(),
        get().loadSettings(),
      ]);
      void get().loadAgents();
      void get().loadLogs();
      void get().loadArtifacts();
      void get().loadRecovery();
    },

    async checkBackend() {
      set({ backend: "checking", backendError: null });
      try {
        await api.health();
        set({ backend: "online", backendError: null });
        return true;
      } catch (error) {
        set({
          backend: "offline",
          backendError: errorMessage(error),
        });
        return false;
      }
    },

    connect() {
      const active = getChatClient();
      if (wiredClient !== active) {
        active.onStatus((connection) => set({ connection }));
        active.onMessage((frame) => get().handleFrame(frame));
        active.onNotice((notice) =>
          set((state) => ({ notices: [...state.notices, notice].slice(-50) })),
        );
        wiredClient = active;
      }
      active.connect();
    },

    reconnect() {
      const active = getChatClient();
      active.close();
      set({ connection: "connecting" });
      get().connect();
    },

    pushNotice(notice) {
      set((state) => ({ notices: [...state.notices, notice].slice(-50) }));
    },

    clearNotices() {
      set({ notices: [] });
    },

    handleFrame(frame) {
      set((state) => {
        const live = applyFrame(state.live, frame);
        if (frame.kind !== "event") return { live };

        const record: EventRecord = {
          seq: state.live.nextSeq,
          event: frame.event as AgentEventName,
          timestamp: frame.timestamp,
          session_id: frame.session_id,
          payload: frame.payload,
          received_at: nowIso(),
        };
        const events = [...state.events, record].slice(-MAX_EVENTS);
        const runId =
          typeof frame.payload.run_id === "string" && frame.payload.run_id !== ""
            ? frame.payload.run_id
            : state.runId;
        return { live, events, runId };
      });
    },

    sendChat(content) {
      const text = content.trim();
      if (text === "") return false;
      // "ask" goes to the configured provider (the real web LLM) and the answer
      // comes back as assistant_delta frames; the M0 echo frame stays available
      // for the compatibility test and is not what a user wants here.
      const sent = getChatClient().send({ type: "ask", content: text });
      if (!sent) return false;
      set((state) => ({
        live: {
          ...state.live,
          messages: [
            ...state.live.messages,
            localMessage(text, "user", state.live.nextSeq),
          ],
          nextSeq: state.live.nextSeq + 1,
        },
      }));
      return true;
    },

    async startRun(request) {
      const task = request.task.trim();
      if (task === "") return false;

      const frame: Extract<ChatClientFrame, { type: "run" }> = {
        type: "run",
        task,
        mode: request.mode,
      };
      if (request.max_steps !== undefined) frame.max_steps = request.max_steps;
      if (request.max_rounds !== undefined) frame.max_rounds = request.max_rounds;
      if (request.auto_confirm !== undefined) frame.auto_confirm = request.auto_confirm;

      set((state) => ({
        runMode: request.mode,
        runTask: task,
        live: {
          ...state.live,
          running: true,
          runStatus: "started",
          messages: [...state.live.messages, localMessage(task, "user", state.live.nextSeq)],
          nextSeq: state.live.nextSeq + 1,
        },
      }));

      const sent = getChatClient().send(frame);
      if (sent) return true;

      // No socket: the REST surface accepts the same run request.
      try {
        const accepted = await api.startRun({
          task,
          mode: request.mode,
          ...(request.max_steps !== undefined ? { max_steps: request.max_steps } : {}),
          ...(request.max_rounds !== undefined ? { max_rounds: request.max_rounds } : {}),
          ...(request.auto_confirm !== undefined ? { auto_confirm: request.auto_confirm } : {}),
        });
        set({ runId: accepted.run_id, backend: "online", backendError: null });
        return true;
      } catch (error) {
        set((state) => ({
          live: { ...state.live, running: false, runStatus: "error" },
          notices: [...state.notices, errorMessage(error)].slice(-50),
          backend: isOfflineError(error) ? "offline" : state.backend,
          backendError: isOfflineError(error) ? errorMessage(error) : state.backendError,
        }));
        return false;
      }
    },

    async stopRun() {
      const runId = get().runId;
      getChatClient().send(runId ? { type: "stop", run_id: runId } : { type: "stop" });
      try {
        await api.stopRun(runId);
      } catch (error) {
        set((state) => ({
          notices: [...state.notices, "stop: " + errorMessage(error)].slice(-50),
        }));
      }
      set((state) => ({ live: { ...state.live, running: false, runStatus: "stopped" } }));
    },

    requestSnapshot() {
      getChatClient().send({ type: "snapshot" });
    },

    respondConfirm(requestId, choice) {
      set((state) => ({
        live: {
          ...state.live,
          confirmations: state.live.confirmations.map((entry) =>
            entry.request_id === requestId ? { ...entry, answered_with: choice } : entry,
          ),
        },
      }));

      // The socket carries the answer when it is up; the REST route is the
      // fallback so a confirmation is always answerable.
      const sent = getChatClient().send({
        type: "confirm",
        request_id: requestId,
        choice,
      });
      if (sent) return;

      void api
        .confirm({ request_id: requestId, choice })
        .catch((error: unknown) => {
          get().pushNotice("confirm: " + errorMessage(error));
        });
    },

    async loadSessions() {
      set((state) => ({ sessions: { ...state.sessions, status: "loading", error: null } }));
      try {
        const body = await api.sessions();
        set({
          sessions: { data: body.sessions, status: "ready", error: null },
          activeSessionId: body.active_session_id ?? null,
          sessionRecovered: body.recovered,
          backend: "online",
          backendError: null,
        });
      } catch (error) {
        const offline = isOfflineError(error);
        set((state) => ({
          sessions: { ...state.sessions, status: "error", error: errorMessage(error) },
          backend: offline ? "offline" : state.backend,
          backendError: offline ? errorMessage(error) : state.backendError,
        }));
      }
    },

    async newSession(title) {
      try {
        const created = await api.createSession(title);
        await get().loadSessions();
        if (created.active_session_id) {
          await get().switchSession(created.active_session_id);
        }
      } catch (error) {
        get().pushNotice("new session: " + errorMessage(error));
      }
    },

    async switchSession(sessionId) {
      set({ activeSessionId: sessionId });
      try {
        const body = await api.messages(sessionId);
        set((state) => ({
          live: {
            ...emptyTimeline(),
            messages: transcriptToMessages(body.messages),
            nextSeq: body.messages.length + 1,
            projectState: state.live.projectState,
          },
          events: [],
          replay: { active: false, index: -1, playing: false, view: emptyTimeline() },
          backend: "online",
          backendError: null,
        }));
      } catch (error) {
        const offline = isOfflineError(error);
        set((state) => ({
          notices: [...state.notices, "messages: " + errorMessage(error)].slice(-50),
          backend: offline ? "offline" : state.backend,
          backendError: offline ? errorMessage(error) : state.backendError,
        }));
      }
    },

    async archiveSession(sessionId) {
      try {
        await api.archiveSession(sessionId);
        await get().loadSessions();
      } catch (error) {
        get().pushNotice("archive: " + errorMessage(error));
      }
    },

    setSessionQuery(query) {
      set({ sessionQuery: query });
    },

    async loadProjectState() {
      try {
        const state = await api.projectState();
        set((current) => ({
          live: { ...current.live, projectState: state },
          backend: "online",
          backendError: null,
        }));
      } catch (error) {
        const offline = isOfflineError(error);
        set((current) => ({
          backend: offline ? "offline" : current.backend,
          backendError: offline ? errorMessage(error) : current.backendError,
          notices: offline ? current.notices : [...current.notices, "project state: " + errorMessage(error)].slice(-50),
        }));
      }
    },

    async loadMemory() {
      loading("memory");
      try {
        const body = await api.memory();
        set({ memory: { data: body.memories, status: "ready", error: null }, backend: "online", backendError: null });
      } catch (error) {
        fail("memory", error);
      }
    },

    async loadLogs() {
      loading("logs");
      try {
        const body = await api.logs();
        set({ logs: { data: body, status: "ready", error: null }, backend: "online", backendError: null });
      } catch (error) {
        fail("logs", error);
      }
    },

    async loadAgents() {
      loading("agents");
      try {
        const body = await api.agents();
        set({ agents: { data: body, status: "ready", error: null }, backend: "online", backendError: null });
      } catch (error) {
        fail("agents", error);
      }
    },

    async loadArtifacts() {
      loading("artifacts");
      try {
        const body = await api.artifacts();
        set({ artifacts: { data: body, status: "ready", error: null }, backend: "online", backendError: null });
      } catch (error) {
        fail("artifacts", error);
      }
    },

    async loadRecovery() {
      loading("recovery");
      try {
        const body = await api.recovery();
        set({ recovery: { data: body, status: "ready", error: null }, backend: "online", backendError: null });
      } catch (error) {
        fail("recovery", error);
      }
    },

    async loadContext(task) {
      loading("context");
      try {
        const body = await api.context({ task });
        set({ context: { data: body, status: "ready", error: null }, backend: "online", backendError: null });
      } catch (error) {
        fail("context", error);
      }
    },

    async loadSettings() {
      set((state) => ({ settings: { ...state.settings, status: "loading", error: null } }));
      try {
        const body = await api.settings();
        set({
          settings: { data: body, status: "ready", error: null },
          settingsDraft: body,
          backend: "online",
          backendError: null,
        });
      } catch (error) {
        const offline = isOfflineError(error);
        set((state) => ({
          settings: { ...state.settings, status: "error", error: errorMessage(error) },
          backend: offline ? "offline" : state.backend,
          backendError: offline ? errorMessage(error) : state.backendError,
        }));
      }
    },

    async loadAll() {
      await Promise.all([
        get().loadProjectState(),
        get().loadMemory(),
        get().loadLogs(),
        get().loadAgents(),
        get().loadArtifacts(),
        get().loadRecovery(),
      ]);
    },

    setSettingsDraft(next) {
      set({ settingsDraft: next });
    },

    async saveSettings(next) {
      const document = next ?? get().settingsDraft;
      if (!document) return;
      set({ saveStatus: "loading", saveError: null });
      try {
        const saved = await api.saveSettings(document);
        set({
          settings: { data: saved, status: "ready", error: null },
          settingsDraft: saved,
          saveStatus: "ready",
          saveError: null,
          backend: "online",
          backendError: null,
        });
      } catch (error) {
        set((state) => ({
          saveStatus: "error",
          saveError: errorMessage(error),
          backend: isOfflineError(error) ? "offline" : state.backend,
          backendError: isOfflineError(error) ? errorMessage(error) : state.backendError,
        }));
      }
    },

    startReplay() {
      set((state) => ({
        replay: {
          active: true,
          index: state.events.length - 1,
          playing: false,
          view: foldEvents(state.events),
        },
      }));
    },

    stopReplay() {
      set({ replay: { active: false, index: -1, playing: false, view: emptyTimeline() } });
    },

    setReplayIndex(index) {
      set((state) => {
        const clamped = Math.max(-1, Math.min(index, state.events.length - 1));
        return {
          replay: {
            active: true,
            index: clamped,
            playing: false,
            view: foldEvents(state.events, clamped),
          },
        };
      });
    },

    stepReplay(delta) {
      get().setReplayIndex(get().replay.index + delta);
    },

    toggleReplayPlay() {
      set((state) => ({
        replay: { ...state.replay, active: true, playing: !state.replay.playing },
      }));
    },
  };
});

/** The timeline the UI renders: the replay view while Replay is active. */
export function selectTimeline(state: AppStore): TimelineState {
  return state.replay.active ? state.replay.view : state.live;
}

/** Restore the initial state (tests). */
export function resetAppStore(): void {
  setChatClient(null);
  useAppStore.setState({ ...initialState, live: emptyTimeline(), replay: { active: false, index: -1, playing: false, view: emptyTimeline() } });
}

export type { ToolCallFields };