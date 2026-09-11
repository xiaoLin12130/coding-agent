import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientFrame, ServerFrame } from "../types";
import {
  createChatClient,
  parseServerFrame,
  resolveWsUrl,
  type WebSocketLike,
} from "./ws";

class FakeSocket implements WebSocketLike {
  readyState = 0;
  sent: string[] = [];
  closed = false;
  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.readyState = 3;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  deliver(data: unknown): void {
    this.onmessage?.({ data });
  }

  serverClose(): void {
    this.readyState = 3;
    this.onclose?.({});
  }
}

function setup() {
  const sockets: FakeSocket[] = [];
  const client = createChatClient({
    url: "ws://test/ws",
    factory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    reconnectBaseMs: 10,
    reconnectMaxMs: 20,
  });
  return { client, sockets };
}

describe("resolveWsUrl", () => {
  it("uses ws:// for http pages and the /ws path", () => {
    expect(resolveWsUrl({ protocol: "http:", host: "localhost:5173" })).toBe(
      "ws://localhost:5173/ws",
    );
  });

  it("uses wss:// for https pages", () => {
    expect(resolveWsUrl({ protocol: "https:", host: "example.test" })).toBe(
      "wss://example.test/ws",
    );
  });

  it("honours an explicit override", () => {
    expect(
      resolveWsUrl({ protocol: "http:", host: "localhost:5173" }, "ws://127.0.0.1:9000/ws"),
    ).toBe("ws://127.0.0.1:9000/ws");
  });
});

describe("parseServerFrame", () => {
  const valid = {
    type: "message",
    message: {
      id: "m1",
      role: "assistant",
      content: "Echo: hi",
      created_at: "2024-01-01T00:00:00Z",
    },
  };

  it("accepts a well formed message frame object", () => {
    expect(parseServerFrame(valid)).toEqual(valid);
  });

  it("accepts a well formed frame arriving as JSON text", () => {
    expect(parseServerFrame(JSON.stringify(valid))).toEqual(valid);
  });

  it("accepts an error frame and fills missing fields", () => {
    expect(parseServerFrame({ type: "error", error: {} })).toEqual({
      type: "error",
      error: { code: "unknown_error", message: "Unspecified server error." },
    });
  });

  it("returns null for malformed JSON text", () => {
    expect(parseServerFrame("{not json")).toBeNull();
  });

  it("returns null for unknown frame types", () => {
    expect(parseServerFrame({ type: "tool_call", name: "rm -rf /" })).toBeNull();
  });

  it("returns null for message frames with missing fields", () => {
    expect(parseServerFrame({ type: "message", message: { id: "x" } })).toBeNull();
    expect(parseServerFrame({ type: "message" })).toBeNull();
  });

  it("returns null for non object payloads", () => {
    expect(parseServerFrame(null)).toBeNull();
    expect(parseServerFrame([valid])).toBeNull();
    expect(parseServerFrame(42)).toBeNull();
  });
});

describe("createChatClient", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports connecting then connected", () => {
    const { client, sockets } = setup();
    const seen: string[] = [];
    client.onStatus((status) => seen.push(status));

    client.connect();
    expect(client.getStatus()).toBe("connecting");
    sockets[0].open();
    expect(client.getStatus()).toBe("connected");
    expect(seen).toEqual(["connecting", "connected"]);
  });

  it("sends the exact chat frame shape when open", () => {
    const { client, sockets } = setup();
    client.connect();
    sockets[0].open();

    const frame: ClientFrame = { type: "chat", content: "hello agent" };
    expect(client.send(frame)).toBe(true);
    expect(sockets[0].sent).toEqual(['{"type":"chat","content":"hello agent"}']);
  });

  it("refuses to send and reports a notice while not open", () => {
    const { client } = setup();
    const notices: string[] = [];
    client.onNotice((notice) => notices.push(notice));

    expect(client.send({ type: "chat", content: "hi" })).toBe(false);
    expect(notices).toEqual(["Not connected: the message was not sent."]);
  });

  it("delivers parsed frames and drops unreadable ones without throwing", () => {
    const { client, sockets } = setup();
    const frames: ServerFrame[] = [];
    const notices: string[] = [];
    client.onMessage((frame) => frames.push(frame));
    client.onNotice((notice) => notices.push(notice));

    client.connect();
    sockets[0].open();
    sockets[0].deliver("this is not json");
    sockets[0].deliver(JSON.stringify({
      type: "message",
      message: { id: "m1", role: "assistant", content: "Echo: hi", created_at: "" },
    }));

    expect(notices).toEqual(["Ignored an unreadable frame from the server."]);
    expect(frames).toHaveLength(1);
    expect(frames[0].type).toBe("message");
  });

  it("reconnects with backoff after an unexpected close", () => {
    const { client, sockets } = setup();
    client.connect();
    sockets[0].open();

    sockets[0].serverClose();
    expect(client.getStatus()).toBe("disconnected");
    expect(sockets).toHaveLength(1);

    vi.advanceTimersByTime(10);
    expect(sockets).toHaveLength(2);
    expect(client.getStatus()).toBe("connecting");
  });

  it("does not reconnect after an explicit close", () => {
    const { client, sockets } = setup();
    client.connect();
    sockets[0].open();

    client.close();
    expect(sockets[0].closed).toBe(true);
    vi.advanceTimersByTime(1000);
    expect(sockets).toHaveLength(1);
    expect(client.getStatus()).toBe("disconnected");
  });
});
