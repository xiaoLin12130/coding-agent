/**
 * UI-only types.
 *
 * Backend models are NEVER re-declared here: they are imported from the
 * generated `src/api/schema.d.ts` (see docs/api-protocol.md). This file only
 * describes shapes that exist purely inside the console.
 */

import type {
  AgentEvent,
  ConfirmRequestPayload,
  JsonValue,
  MemoryEntry,
  ProjectState,
  RecoverySnapshot,
  SessionInfo,
  Settings,
} from "../api/schema";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type BackendStatus = "unknown" | "checking" | "online" | "offline";

export type LoadStatus = "idle" | "loading" | "ready" | "error";

export type ConfirmChoice = "reject" | "once" | "session";

export type AgentEventName =
  | "assistant_delta"
  | "tool_call"
  | "tool_result"
  | "state_update"
  | "memory_update"
  | "agent_update"
  | "confirm_request"
  | "error"
  | "done";

/** One M0 compatibility chat message ({"type":"message"} frame). */
export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type UiRole = "system" | "user" | "assistant" | "tool";

/** One line of the chat timeline, whatever its source. */
export type TimelineMessage = {
  id: string;
  role: UiRole;
  content: string;
  created_at: string;
  seq: number;
  /** true while an assistant message is still receiving assistant_delta text */
  streaming?: boolean;
  tool_name?: string | null;
  tool_call_id?: string | null;
};

export type ToolCallStatus = "running" | "ok" | "failed";

/** A tool_call paired with its tool_result by call_id. */
export type ToolCallRecord = {
  call_id: string;
  tool: string;
  args: Record<string, JsonValue>;
  risk: string;
  status: ToolCallStatus;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  ok: boolean | null;
  error_code: string | null;
  summary: string;
  /** unified diff carried by the tool result, when the backend sent one */
  diff: string | null;
  seq: number;
};

/** A confirmation the console has to answer. */
export type PendingConfirmation = {
  request_id: string;
  tool: string;
  risk: string;
  command: string;
  cwd: string;
  impact: string[];
  reasons: string[];
  choices: ConfirmChoice[];
  args: Record<string, JsonValue>;
  created_at: string;
  answered_with: ConfirmChoice | null;
  seq: number;
};

/** One recorded server event, kept for the history list and for Replay. */
export type EventRecord = {
  seq: number;
  event: AgentEventName;
  timestamp: string;
  session_id: string;
  payload: Record<string, JsonValue>;
  received_at: string;
};

/** Everything the chat + tool cards are rendered from. */
export type TimelineState = {
  messages: TimelineMessage[];
  toolCalls: ToolCallRecord[];
  confirmations: PendingConfirmation[];
  projectState: ProjectState | null;
  memory: MemoryEntry[] | null;
  recovery: RecoverySnapshot | null;
  runStatus: string;
  runId: string | null;
  running: boolean;
  notices: string[];
  nextSeq: number;
};

export type RunMode = "single" | "multi";

/** A request to start a run from the composer or the Agents panel. */
export type RunRequest = {
  task: string;
  mode: RunMode;
  max_steps?: number;
  max_rounds?: number;
  auto_confirm?: boolean;
};

export type SessionRecord = SessionInfo;

export type SettingsDocument = Settings;

export type AgentEventRecord = AgentEvent;

export type { ConfirmRequestPayload, JsonValue, MemoryEntry, ProjectState, RecoverySnapshot };
