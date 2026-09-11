/**
 * Typed REST client for the frozen backend contract.
 *
 * Every response type is imported from the generated `src/api/schema.d.ts`
 * (docs/api-protocol.md), so no backend model is declared twice.
 *
 * Failures are normalised into ApiError with a `kind`:
 *   "network"  the backend is not answering (the console shows "backend offline")
 *   "http"     the backend answered with an error status
 *   "parse"    the backend answered with something that is not the expected JSON
 */

import type {
  AgentConfirmAck,
  AgentConfirmRequest,
  AgentRunAccepted,
  AgentRunRequest,
  AgentStateResponse,
  AgentsResponse,
  ArtifactsResponse,
  BuiltContext,
  Health,
  LogsResponse,
  MemoryResponse,
  MessagesResponse,
  ProjectState,
  RecoveryRunsResponse,
  RecoverySnapshot,
  SessionArchiveResponse,
  SessionCreateResponse,
  SessionDetail,
  SessionListResponse,
  Settings,
} from "./schema";

export type ApiErrorKind = "network" | "http" | "parse";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly path: string;

  constructor(kind: ApiErrorKind, path: string, message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.path = path;
  }
}

export function isOfflineError(error: unknown): boolean {
  return error instanceof ApiError && error.kind === "network";
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "未知错误";
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  signal?: AbortSignal;
  /** query string parameters; null/undefined entries are dropped */
  query?: Record<string, string | number | boolean | null | undefined>;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const suffix = params.toString();
  return suffix === "" ? path : path + "?" + suffix;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = buildUrl(path, options.query);
  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    throw new ApiError(
      "network",
      path,
      "后端离线：" + path + " could not be reached.",
      0,
    );
  }
  if (!response.ok) {
    throw new ApiError("http", path, path + " responded with HTTP " + response.status, response.status);
  }
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("parse", path, path + " returned a body that is not JSON", response.status);
  }
}

async function requestText(path: string, query?: RequestOptions["query"]): Promise<string> {
  const url = buildUrl(path, query);
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new ApiError("http", path, path + " responded with HTTP " + response.status, response.status);
    }
    return await response.text();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("network", path, "Backend offline: " + path + " could not be reached.");
  }
}

// -- endpoints --------------------------------------------------------------

/** A settings document must carry every documented section. */
function validateSettings(value: unknown): Settings {
  const record = (value ?? {}) as Record<string, unknown>;
  const sections = [
    "provider",
    "browser",
    "safety",
    "confirmation",
    "context_thresholds",
    "multi_agent",
  ];
  const missing = sections.filter(
    (key) => typeof record[key] !== "object" || record[key] === null,
  );
  if (typeof record.working_dir !== "string") missing.push("working_dir");
  if (missing.length > 0) {
    throw new ApiError(
      "parse",
      "/api/settings",
      "/api/settings did not return a settings document (missing " + missing.join(", ") + ")",
    );
  }
  return value as Settings;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/api/health", { signal }),

  projectState: (signal?: AbortSignal) =>
    request<ProjectState>("/api/project_state", { signal }),

  memory: (signal?: AbortSignal) => request<MemoryResponse>("/api/memory", { signal }),

  sessions: (signal?: AbortSignal) =>
    request<SessionListResponse>("/api/sessions", { signal }),

  createSession: (title?: string, signal?: AbortSignal) =>
    request<SessionCreateResponse>("/api/sessions", {
      method: "POST",
      // The contract documents a JSON body; the current backend reads ?title=.
      // Sending both keeps the console working against either implementation.
      query: title ? { title } : undefined,
      body: { title: title ?? null },
      signal,
    }),

  session: (id: string, signal?: AbortSignal) =>
    request<SessionDetail>("/api/sessions/" + encodeURIComponent(id), { signal }),

  archiveSession: (id: string, signal?: AbortSignal) =>
    request<SessionArchiveResponse>(
      "/api/sessions/" + encodeURIComponent(id) + "/archive",
      { method: "POST", signal },
    ),

  messages: (sessionId?: string | null, limit?: number, signal?: AbortSignal) =>
    request<MessagesResponse>("/api/messages", {
      query: { session_id: sessionId ?? undefined, limit },
      signal,
    }),

  context: (
    query: { task?: string; system?: string; memory_query?: string; session_id?: string },
    signal?: AbortSignal,
  ) => request<BuiltContext>("/api/context", { query, signal }),

  recovery: (signal?: AbortSignal) => request<RecoverySnapshot>("/api/recovery", { signal }),

  recoveryRuns: (signal?: AbortSignal) =>
    request<RecoveryRunsResponse>("/api/recovery/runs", { signal }),

  settings: async (signal?: AbortSignal) =>
    validateSettings(await request<Settings>("/api/settings", { signal })),

  saveSettings: async (settings: Settings, signal?: AbortSignal) =>
    validateSettings(
      await request<Settings>("/api/settings", { method: "PUT", body: settings, signal }),
    ),

  logs: (limit = 200, signal?: AbortSignal) =>
    request<LogsResponse>("/api/logs", { query: { limit }, signal }),

  agents: (signal?: AbortSignal) => request<AgentsResponse>("/api/agents", { signal }),

  agentState: (signal?: AbortSignal) =>
    request<AgentStateResponse>("/api/agent/state", { signal }),

  artifacts: (signal?: AbortSignal) =>
    request<ArtifactsResponse>("/api/observability/artifacts", { signal }),

  artifactUrl: (path: string) =>
    "/api/observability/file?path=" + encodeURIComponent(path),

  artifactText: (path: string) =>
    requestText("/api/observability/file", { path }),

  startRun: (payload: AgentRunRequest, signal?: AbortSignal) =>
    request<AgentRunAccepted>("/api/agent/run", { method: "POST", body: payload, signal }),

  stopRun: (runId?: string | null, signal?: AbortSignal) =>
    request<{ run_id: string | null; stopped: boolean }>("/api/agent/stop", {
      method: "POST",
      body: { run_id: runId ?? null },
      signal,
    }),

  confirm: (payload: AgentConfirmRequest, signal?: AbortSignal) =>
    request<AgentConfirmAck>("/api/agent/confirm", { method: "POST", body: payload, signal }),
};

export type Api = typeof api;
