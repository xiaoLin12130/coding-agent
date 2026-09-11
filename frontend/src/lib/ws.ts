/**
 * WebSocket client for /ws (docs/api-protocol.md).
 *
 * Two server frame families share the socket:
 *
 *   M0 compatibility  {"type":"message","message":{...}} / {"type":"error",...}
 *   documented events {"event":"...","timestamp":...,"session_id":...,"payload":{...}}
 *
 * Every inbound frame is DATA: malformed frames are reported through the
 * notice channel and dropped. They never throw out of the socket handlers.
 *
 * Client frames: chat (M0 echo) | ask (the real model, streamed) | run | stop |
 * confirm | snapshot.
 */

import type { JsonValue } from "../api/schema";
import type { AgentEventName, ChatMessage, ConfirmChoice, ConnectionStatus, RunMode } from "../types/ui";

export const WS_OPEN = 1;
export const WS_CONNECTING = 0;

export type WebSocketLike = {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: ((event: unknown) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
};

export type WebSocketFactory = (url: string) => WebSocketLike;

/** Every frame the console can send. */
export type ChatClientFrame =
  | { type: "chat"; content: string }
  | { type: "ask"; content: string }
  | {
      type: "run";
      task: string;
      mode: RunMode;
      max_steps?: number;
      max_rounds?: number;
      auto_confirm?: boolean;
    }
  | { type: "stop"; run_id?: string }
  | { type: "confirm"; run_id?: string; request_id: string; choice: ConfirmChoice }
  | { type: "snapshot" };

/** Back-compat alias: the M0 client only ever sent chat frames. */
export type ClientFrame = ChatClientFrame;

export type ErrorInfo = { code: string; message: string };

/** Normalised inbound frame. */
export type ParsedFrame =
  | { kind: "message"; message: ChatMessage }
  | { kind: "error"; error: ErrorInfo }
  | {
      kind: "event";
      event: AgentEventName;
      timestamp: string;
      session_id: string;
      payload: Record<string, JsonValue>;
      request_id?: string;
      tool_call_id?: string;
      agent_id?: string;
    };

/** Back-compat alias used across the app. */
export type ServerFrame = ParsedFrame;

export type WebSocketMessageFrame = Extract<ParsedFrame, { kind: "message" }>;
export type WebSocketErrorFrame = Extract<ParsedFrame, { kind: "error" }>;
export type WebSocketEventFrame = Extract<ParsedFrame, { kind: "event" }>;

export type ChatClient = {
  connect(): void;
  send(frame: ChatClientFrame): boolean;
  close(): void;
  getStatus(): ConnectionStatus;
  onMessage(handler: (frame: ParsedFrame) => void): () => void;
  onStatus(handler: (status: ConnectionStatus) => void): () => void;
  onNotice(handler: (notice: string) => void): () => void;
};

export type ChatClientOptions = {
  url?: string;
  factory?: WebSocketFactory;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
};

const EVENT_NAMES: ReadonlySet<string> = new Set<AgentEventName>([
  "assistant_delta",
  "tool_call",
  "tool_result",
  "state_update",
  "memory_update",
  "agent_update",
  "confirm_request",
  "error",
  "done",
]);

const defaultFactory: WebSocketFactory = (url) => new WebSocket(url) as unknown as WebSocketLike;

/** Derive the socket URL from the current page, unless explicitly overridden. */
export function resolveWsUrl(
  location: { protocol: string; host: string } = window.location,
  override?: string,
): string {
  if (override && override.trim() !== "") return override.trim();
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return scheme + "//" + location.host + "/ws";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/**
 * Turn one raw inbound payload into a known frame, or null when it is
 * malformed/unrecognised. Never throws.
 */
export function parseServerFrame(raw: unknown): ParsedFrame | null {
  let data: unknown = raw;
  if (typeof raw === "string") {
    try {
      data = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!isRecord(data)) return null;

  // (a) M0 compatibility family -------------------------------------------
  if (data.type === "message") {
    const message = data.message;
    if (!isRecord(message)) return null;
    const { id, role, content, created_at } = message;
    if (typeof id !== "string" || typeof content !== "string") return null;
    if (role !== "user" && role !== "assistant") return null;
    return {
      kind: "message",
      message: { id, role, content, created_at: typeof created_at === "string" ? created_at : "" },
    };
  }

  if (data.type === "error") {
    const error = data.error;
    if (!isRecord(error)) return null;
    return {
      kind: "error",
      error: {
        code: typeof error.code === "string" ? error.code : "unknown_error",
        message: typeof error.message === "string" ? error.message : "未指定的服务器错误。",
      },
    };
  }

  // (b) documented event envelope -----------------------------------------
  if (typeof data.event === "string" && EVENT_NAMES.has(data.event)) {
    if (!isRecord(data.payload)) return null;
    return {
      kind: "event",
      event: data.event as AgentEventName,
      timestamp: typeof data.timestamp === "string" ? data.timestamp : "",
      session_id: typeof data.session_id === "string" ? data.session_id : "",
      payload: data.payload as Record<string, JsonValue>,
      request_id: optionalString(data.request_id),
      tool_call_id: optionalString(data.tool_call_id),
      agent_id: optionalString(data.agent_id),
    };
  }

  return null;
}

export function createChatClient(options: ChatClientOptions = {}): ChatClient {
  const factory = options.factory ?? defaultFactory;
  const url =
    options.url ??
    resolveWsUrl(window.location, import.meta.env.VITE_WS_URL as string | undefined);
  const baseDelay = options.reconnectBaseMs ?? 500;
  const maxDelay = options.reconnectMaxMs ?? 10_000;

  let socket: WebSocketLike | null = null;
  let status: ConnectionStatus = "disconnected";
  let attempts = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let closedByUser = false;

  const messageHandlers = new Set<(frame: ParsedFrame) => void>();
  const statusHandlers = new Set<(next: ConnectionStatus) => void>();
  const noticeHandlers = new Set<(notice: string) => void>();

  const setStatus = (next: ConnectionStatus): void => {
    status = next;
    statusHandlers.forEach((handler) => handler(next));
  };

  const notify = (notice: string): void => {
    noticeHandlers.forEach((handler) => handler(notice));
  };

  const clearRetry = (): void => {
    if (retryTimer !== null) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
  };

  const scheduleRetry = (): void => {
    clearRetry();
    const delay = Math.min(baseDelay * 2 ** attempts, maxDelay);
    attempts += 1;
    setStatus("disconnected");
    retryTimer = setTimeout(() => {
      retryTimer = null;
      connect();
    }, delay);
  };

  function connect(): void {
    if (socket && (socket.readyState === WS_OPEN || socket.readyState === WS_CONNECTING)) return;
    closedByUser = false;
    clearRetry();
    setStatus("connecting");

    const next = factory(url);
    socket = next;

    next.onopen = () => {
      attempts = 0;
      setStatus("connected");
    };
    next.onmessage = (event) => {
      const frame = parseServerFrame(event.data);
      if (frame === null) {
        notify("Ignored an unreadable frame from the server.");
        return;
      }
      messageHandlers.forEach((handler) => handler(frame));
    };
    next.onerror = () => {
      // A close always follows; reconnection is handled there.
    };
    next.onclose = () => {
      if (socket === next) socket = null;
      if (closedByUser) {
        setStatus("disconnected");
        return;
      }
      scheduleRetry();
    };
  }

  return {
    connect,
    send(frame: ChatClientFrame): boolean {
      if (!socket || socket.readyState !== WS_OPEN) {
        notify("Not connected: the frame was not sent.");
        return false;
      }
      socket.send(JSON.stringify(frame));
      return true;
    },
    close(): void {
      closedByUser = true;
      clearRetry();
      const current = socket;
      socket = null;
      current?.close();
      setStatus("disconnected");
    },
    getStatus: () => status,
    onMessage(handler) {
      messageHandlers.add(handler);
      return () => messageHandlers.delete(handler);
    },
    onStatus(handler) {
      statusHandlers.add(handler);
      return () => statusHandlers.delete(handler);
    },
    onNotice(handler) {
      noticeHandlers.add(handler);
      return () => noticeHandlers.delete(handler);
    },
  };
}
