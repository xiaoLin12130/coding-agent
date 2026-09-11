/**
 * Framework-free WebSocket client for the /ws endpoint.
 *
 * Contract:
 *   client -> {"type":"chat","content":"..."}
 *   server -> {"type":"message","message":{...}}
 *   server -> {"type":"error","error":{"code":"...","message":"..."}}
 *
 * Every inbound frame is treated as data: unreadable frames are reported
 * through the notice channel and dropped, they never throw out of the
 * socket handlers.
 */

import type {
  ClientFrame,
  ConnectionStatus,
  ServerFrame,
} from "../types";

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

export type ChatClient = {
  connect(): void;
  send(frame: ClientFrame): boolean;
  close(): void;
  getStatus(): ConnectionStatus;
  onMessage(handler: (frame: ServerFrame) => void): () => void;
  onStatus(handler: (status: ConnectionStatus) => void): () => void;
  onNotice(handler: (notice: string) => void): () => void;
};

export type ChatClientOptions = {
  url?: string;
  factory?: WebSocketFactory;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
};

const defaultFactory: WebSocketFactory = (url) =>
  new WebSocket(url) as unknown as WebSocketLike;

/** Derive the socket URL from the current page, unless explicitly overridden. */
export function resolveWsUrl(
  location: { protocol: string; host: string } = window.location,
  override?: string,
): string {
  if (override && override.trim() !== "") return override.trim();
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Turn one raw inbound payload into a known frame, or null when it is
 * malformed/unrecognised. Never throws.
 */
export function parseServerFrame(raw: unknown): ServerFrame | null {
  let data: unknown = raw;
  if (typeof raw === "string") {
    try {
      data = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!isRecord(data)) return null;

  if (data.type === "message") {
    const message = data.message;
    if (!isRecord(message)) return null;
    const { id, role, content, created_at } = message;
    if (typeof id !== "string" || typeof content !== "string") return null;
    if (role !== "user" && role !== "assistant") return null;
    return {
      type: "message",
      message: {
        id,
        role,
        content,
        created_at: typeof created_at === "string" ? created_at : "",
      },
    };
  }

  if (data.type === "error") {
    const error = data.error;
    if (!isRecord(error)) return null;
    return {
      type: "error",
      error: {
        code: typeof error.code === "string" ? error.code : "unknown_error",
        message:
          typeof error.message === "string"
            ? error.message
            : "Unspecified server error.",
      },
    };
  }

  return null;
}

export function createChatClient(options: ChatClientOptions = {}): ChatClient {
  const factory = options.factory ?? defaultFactory;
  const url =
    options.url ??
    resolveWsUrl(window.location, import.meta.env.VITE_WS_URL as
      | string
      | undefined);
  const baseDelay = options.reconnectBaseMs ?? 500;
  const maxDelay = options.reconnectMaxMs ?? 10_000;

  let socket: WebSocketLike | null = null;
  let status: ConnectionStatus = "disconnected";
  let attempts = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let closedByUser = false;

  const messageHandlers = new Set<(frame: ServerFrame) => void>();
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
    if (socket && (socket.readyState === WS_OPEN || socket.readyState === WS_CONNECTING)) {
      return;
    }
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
    send(frame: ClientFrame): boolean {
      if (!socket || socket.readyState !== WS_OPEN) {
        notify("Not connected: the message was not sent.");
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
