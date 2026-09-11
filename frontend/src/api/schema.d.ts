/* eslint-disable */
// ---------------------------------------------------------------------------
// GENERATED FILE - DO NOT EDIT BY HAND.
//
// Source: scripts/openapi.snapshot.json (frozen contract snapshot)
// Regenerate with: npm run gen:api  (see scripts/gen-api-types.mjs)
//
// The backend Pydantic models are the single source of truth
// (docs/api-protocol.md), so every backend model exists exactly once, here.
// ---------------------------------------------------------------------------

/** Any JSON value the backend may put in an untyped field. */
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

/** Every schema the backend published, addressable by name. */
export interface ApiSchemas {
  AgentConfirmAck: AgentConfirmAck;
  AgentConfirmRequest: AgentConfirmRequest;
  AgentEvent: AgentEvent;
  AgentEventEnvelope: AgentEventEnvelope;
  AgentRole: AgentRole;
  AgentRunAccepted: AgentRunAccepted;
  AgentRunInfo: AgentRunInfo;
  AgentRunRequest: AgentRunRequest;
  AgentStateResponse: AgentStateResponse;
  AgentStopRequest: AgentStopRequest;
  AgentStopResult: AgentStopResult;
  AgentUpdatePayload: AgentUpdatePayload;
  AgentsResponse: AgentsResponse;
  ArtifactsResponse: ArtifactsResponse;
  AssistantDeltaPayload: AssistantDeltaPayload;
  BrowserSettings: BrowserSettings;
  BuiltContext: BuiltContext;
  ConfirmRequestPayload: ConfirmRequestPayload;
  ConfirmationSettings: ConfirmationSettings;
  ContextPressure: ContextPressure;
  ContextSection: ContextSection;
  ContextThresholdSettings: ContextThresholdSettings;
  DonePayload: DonePayload;
  ErrorPayload: ErrorPayload;
  Health: Health;
  LogsResponse: LogsResponse;
  MemoryEntry: MemoryEntry;
  MemoryResponse: MemoryResponse;
  MemoryUpdatePayload: MemoryUpdatePayload;
  MessagesResponse: MessagesResponse;
  MultiAgentSettings: MultiAgentSettings;
  ProjectState: ProjectState;
  ProviderSettings: ProviderSettings;
  RecoveryRunsResponse: RecoveryRunsResponse;
  RecoverySnapshot: RecoverySnapshot;
  RunArtifacts: RunArtifacts;
  RunRecoveryPlan: RunRecoveryPlan;
  SafetySettings: SafetySettings;
  SessionArchiveResponse: SessionArchiveResponse;
  SessionCreateRequest: SessionCreateRequest;
  SessionCreateResponse: SessionCreateResponse;
  SessionDetail: SessionDetail;
  SessionInfo: SessionInfo;
  SessionListResponse: SessionListResponse;
  Settings: Settings;
  StateUpdatePayload: StateUpdatePayload;
  TodoItem: TodoItem;
  ToolCallLogEntry: ToolCallLogEntry;
  ToolCallPayload: ToolCallPayload;
  ToolResultPayload: ToolResultPayload;
  TranscriptEntry: TranscriptEntry;
}

export interface AgentConfirmAck {
  accepted: boolean;
}

/** POST /api/agent/confirm and the WS confirm frame. */
export interface AgentConfirmRequest {
  run_id?: string | null;
  request_id: string;
  choice: "reject" | "once" | "session";
}

/** Runtime event (also carried in the WS envelope payload). */
export interface AgentEvent {
  type: string;
  step: number;
  at: string;
  message: string;
  tool?: string | null;
  ok?: boolean | null;
  data: Record<string, JsonValue>;
}

/** Server -> client event frame (docs/api-protocol.md). */
export interface AgentEventEnvelope {
  event: "assistant_delta" | "tool_call" | "tool_result" | "state_update" | "memory_update" | "agent_update" | "confirm_request" | "error" | "done";
  timestamp: string;
  session_id: string;
  payload: Record<string, JsonValue>;
  request_id?: string | null;
  tool_call_id?: string | null;
  agent_id?: string | null;
}

export interface AgentRole {
  name: string;
  purpose: string;
  allowed_tools: string[];
  max_steps: number;
  verdict_kind?: string;
}

export interface AgentRunAccepted {
  run_id: string;
  accepted: boolean;
}

/** One run as the console lists it. */
export interface AgentRunInfo {
  run_id: string;
  task: string;
  mode?: string;
  status: string;
  reason?: string;
  round_count?: number;
  tool_calls: number;
  duration_ms: number;
  started_at?: string | null;
  finished_at?: string | null;
}

/** POST /api/agent/run and the WS run frame. */
export interface AgentRunRequest {
  task: string;
  mode: "single" | "multi";
  max_steps?: number;
  max_rounds?: number;
  auto_confirm?: boolean;
}

/** GET /api/agent/state */
export interface AgentStateResponse {
  running: boolean;
  run_id?: string | null;
  status: string;
  task: string;
  mode: string;
  events: AgentEvent[];
  pending_confirmation?: ConfirmRequestPayload | null;
}

export interface AgentStopRequest {
  run_id?: string | null;
}

export interface AgentStopResult {
  run_id: string | null;
  stopped: boolean;
}

export interface AgentUpdatePayload {
  role?: string | null;
  status: string;
  step?: number;
  message?: string;
  tools_used?: string[];
  run_id?: string;
  task?: string;
  choice?: string;
  stopped?: boolean;
  type?: string;
}

/** GET /api/agents */
export interface AgentsResponse {
  roles: AgentRole[];
  running?: AgentRunInfo | null;
  runs: AgentRunInfo[];
}

/** GET /api/observability/artifacts */
export interface ArtifactsResponse {
  runs: RunArtifacts[];
}

export interface AssistantDeltaPayload {
  text: string;
  type?: string;
  message?: string;
  step?: number;
}

export interface BrowserSettings {
  profile_dir: string;
  artifacts_dir: string;
  headless_allowed: boolean;
}

/** GET /api/context */
export interface BuiltContext {
  sections: ContextSection[];
  dropped_sections: string[];
  budget_chars: number;
  total_chars: number;
  truncated: boolean;
  built_at: string;
}

/** Confirmation the console must answer (the backend also sends 'id'). */
export interface ConfirmRequestPayload {
  request_id?: string;
  id?: string;
  run_id?: string | null;
  tool: string;
  risk: string;
  command?: string;
  cwd?: string;
  impact?: string[];
  reasons?: string[];
  choices: ("reject" | "once" | "session")[];
  arguments?: Record<string, JsonValue>;
  created_at?: string;
  expires_at?: string | null;
  message?: string;
  step?: number;
}

export interface ConfirmationSettings {
  /** ask | auto_once | deny. The backend also accepts the legacy spelling 'once'. */
  policy: "ask" | "auto_once" | "deny" | "once";
  ttl_seconds: number;
}

export interface ContextPressure {
  level: "ok" | "soft" | "hard";
  used_chars: number;
  budget_chars: number;
  ratio: number;
  dropped_sections: string[];
}

export interface ContextSection {
  name: string;
  priority: number;
  content: string;
  original_chars: number;
  included_chars: number;
  truncated: boolean;
  omitted_chars: number;
  reference?: string | null;
  note: string;
}

export interface ContextThresholdSettings {
  soft_ratio: number;
  hard_ratio: number;
  soft_recent_turns: number;
}

export interface DonePayload {
  status: string;
  reason?: string;
  steps?: number;
  tool_calls?: number;
  message?: string;
  step?: number;
  type?: string;
}

export interface ErrorPayload {
  code: string;
  message: string;
  message_text?: string;
  step?: number;
  type?: string;
}

/** GET /api/health */
export interface Health {
  status: string;
  app: string;
  version: string;
}

/** GET /api/logs */
export interface LogsResponse {
  tool_calls: ToolCallLogEntry[];
  events: AgentEvent[];
}

export interface MemoryEntry {
  key: string;
  value: string;
  namespace: string;
  source: string;
  sensitive: boolean;
  source_turn?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** GET /api/memory */
export interface MemoryResponse {
  memories: MemoryEntry[];
}

export interface MemoryUpdatePayload {
  memories?: MemoryEntry[];
  message?: string;
  step?: number;
  type?: string;
}

/** GET /api/messages */
export interface MessagesResponse {
  session_id: string | null;
  message_count: number;
  messages: TranscriptEntry[];
}

export interface MultiAgentSettings {
  enabled: boolean;
  max_rounds: number;
  stall_threshold: number;
  roles: AgentRole[];
}

/** GET /api/project_state - the factual state of the project. */
export interface ProjectState {
  current_milestone: string | null;
  current_task: string | null;
  goal?: string | null;
  todos: TodoItem[];
  files_changed: string[];
  tests: JsonValue[];
  failures: JsonValue[];
  decisions: JsonValue[];
  checkpoint: JsonValue | null;
  commands_run?: JsonValue[];
  git_branch?: string | null;
  cwd?: string | null;
}

export interface ProviderSettings {
  name: string;
  url: string;
  verified: boolean;
  notes: string;
  profiles?: string[];
}

/** GET /api/recovery/runs */
export type RecoveryRunsResponse = RunRecoveryPlan[];

/** GET /api/recovery */
export interface RecoverySnapshot {
  active_session_id: string | null;
  session_message_count: number;
  archived_session_ids: string[];
  memory_count: number;
  latest_run?: RunRecoveryPlan | null;
  context_pressure?: ContextPressure | null;
  taken_at: string;
}

export interface RunArtifacts {
  run_dir: string;
  screenshots: string[];
  dom_snapshots: string[];
  logs: string[];
}

/** One resumable run checkpoint. */
export interface RunRecoveryPlan {
  run_id: string;
  task: string;
  step: number;
  session_id: string;
  status?: string | null;
  checkpoint_path: string;
  resumable: boolean;
  reason: string;
  updated_at?: string | null;
}

export interface SafetySettings {
  project_root: string;
  extra_roots: string[];
  confirm_high_risk: boolean;
  sensitive_names?: string[];
}

/** POST /api/sessions/{id}/archive */
export interface SessionArchiveResponse {
  session_id: string;
  archived: boolean;
  continues_as?: string | null;
}

/** POST /api/sessions body (also accepted as ?title=). */
export interface SessionCreateRequest {
  title?: string | null;
}

/** POST /api/sessions */
export interface SessionCreateResponse {
  active_session_id: string | null;
  created: boolean;
}

/** GET /api/sessions/{id} */
export interface SessionDetail {
  active_session_id: string | null;
  created: boolean;
  recovered: boolean;
  entries: TranscriptEntry[];
  message_count: number;
  turn_count: number;
}

export interface SessionInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived: boolean;
  message_count: number;
  turn_count: number;
  summary_path?: string | null;
  archive_path?: string | null;
  rotated_from?: string | null;
}

/** GET /api/sessions */
export interface SessionListResponse {
  active_session_id: string | null;
  recovered: boolean;
  sessions: SessionInfo[];
}

/** GET/PUT /api/settings */
export interface Settings {
  provider: ProviderSettings;
  browser: BrowserSettings;
  working_dir: string;
  safety: SafetySettings;
  confirmation: ConfirmationSettings;
  context_thresholds: ContextThresholdSettings;
  multi_agent: MultiAgentSettings;
}

export interface StateUpdatePayload {
  project_state?: ProjectState | null;
  snapshot?: RecoverySnapshot | null;
  message?: string;
  step?: number;
  type?: string;
}

export interface TodoItem {
  content: string;
  status: string;
}

/** One line of the append-only tool call log. */
export interface ToolCallLogEntry {
  at: string;
  call_id: string;
  name: string;
  arguments_preview: string;
  ok: boolean;
  error_code?: string | null;
  duration_ms: number;
  idempotent_replay: boolean;
  confirmed: boolean;
}

export interface ToolCallPayload {
  call_id: string;
  tool: string;
  arguments?: Record<string, JsonValue>;
  risk?: string;
  message?: string;
  step?: number;
  type?: string;
}

export interface ToolResultPayload {
  call_id: string;
  tool: string;
  ok: boolean;
  error_code?: string | null;
  duration_ms?: number;
  risk?: string;
  summary?: string;
  message?: string;
  step?: number;
  attempts?: number;
  type?: string;
}

/** One message in a session transcript. */
export interface TranscriptEntry {
  index: number;
  session_id: string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  created_at: string;
  tool_name?: string | null;
  tool_call_id?: string | null;
  meta: Record<string, JsonValue>;
}
