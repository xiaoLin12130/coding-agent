import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatClientFrame, ParsedFrame } from "./ws";
import { createChatClient, parseServerFrame, resolveWsUrl, type WebSocketLike } from "./ws";

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
    expect(resolveWsUrl({ protocol: "http:", host: "127.0.0.1:5273" })).toBe(
      "ws://127.0.0.1:5273/ws",
    );
  });

  it("uses wss:// for https pages", () => {
    expect(resolveWsUrl({ protocol: "https:", host: "example.test" })).toBe(
      "wss://example.test/ws",
    );
  });

  it("honours an explicit override", () => {
    expect(
      resolveWsUrl({ protocol: "http:", host: "localhost:5273" }, "ws://127.0.0.1:9000/ws"),
    ).toBe("ws://127.0.0.1:9000/ws");
  });
});

describe("parseServerFrame - M0 family", () => {
  const valid = {
    type: "message",
    message: { id: "m1", role: "assistant", content: "Echo: hi", created_at: "2024-01-01T00:00:00Z" },
  };

  it("accepts a well formed message frame object and JSON text", () => {
    expect(parseServerFrame(valid)).toEqual({
      kind: "message",
      message: { id: "m1", role: "assistant", content: "Echo: hi", created_at: "2024-01-01T00:00:00Z" },
    });
    expect(parseServerFrame(JSON.stringify(valid))?.kind).toBe("message");
  });

  it("accepts an error frame and fills missing fields", () => {
    expect(parseServerFrame({ type: "error", error: {} })).toEqual({
      kind: "error",
      error: { code: "unknown_error", message: "Unspecified server error." },
    });
  });

  it("returns null for message frames with missing fields", () => {
    expect(parseServerFrame({ type: "message", message: { id: "x" } })).toBeNull();
    expect(parseServerFrame({ type: "message" })).toBeNull();
  });
});

describe("parseServerFrame - documented event envelope", () => {
  const envelope = {
    event: "tool_call",
    timestamp: "2024-01-01T00:00:01Z",
    session_id: "session-1",
    payload: { call_id: "c1", tool: "run_shell", arguments: { command: "ls" }, risk: "high" },
    tool_call_id: "c1",
  };

  it("parses every documented event name", () => {
    const names = [
      "assistant_delta",
      "tool_call",
      "tool_result",
      "state_update",
      "memory_update",
      "agent_update",
      "confirm_request",
      "error",
      "done",
    ] as const;
    for (const event of names) {
      const frame = parseServerFrame({ ...envelope, event, payload: { ...envelope.payload } });
      expect(frame).not.toBeNull();
      expect(frame && frame.kind).toBe("event");
    }
  });

  it("keeps the envelope fields and the correlation ids", () => {
    const frame = parseServerFrame(JSON.stringify(envelope));
    expect(frame).toMatchObject({
      kind: "event",
      event: "tool_call",
      timestamp: "2024-01-01T00:00:01Z",
      session_id: "session-1",
      payload: { call_id: "c1", tool: "run_shell", arguments: { command: "ls" }, risk: "high" },
      tool_call_id: "c1",
    });
  });

  it("ignores malformed frames without throwing", () => {
    const bad: unknown[] = [
      "{not json",
      null,
      42,
      [envelope],
      { event: "tool_call" },
      { event: "tool_call", payload: "not an object" },
      { event: "not_a_documented_event", payload: {} },
      { event: 7, payload: {} },
      {},
    ];
    for (const raw of bad) {
      expect(() => parseServerFrame(raw)).not.toThrow();
      expect(parseServerFrame(raw)).toBeNull();
    }
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

  it("serialises every client frame exactly", () => {
    const { client, sockets } = setup();
    client.connect();
    sockets[0].open();

    const frames: ChatClientFrame[] = [
      { type: "chat", content: "hello agent" },
      { type: "run", task: "fix the bug", mode: "multi", max_steps: 5, auto_confirm: true },
      { type: "stop", run_id: "run-1" },
      { type: "confirm", request_id: "req-1", choice: "session" },
      { type: "snapshot" },
    ];
    for (const frame of frames) expect(client.send(frame)).toBe(true);

    expect(sockets[0].sent).toEqual([
      '{"type":"chat","content":"hello agent"}',
      '{"type":"run","task":"fix the bug","mode":"multi","max_steps":5,"auto_confirm":true}',
      '{"type":"stop","run_id":"run-1"}',
      '{"type":"confirm","request_id":"req-1","choice":"session"}',
      '{"type":"snapshot"}',
    ]);
  });

  it("refuses to send and reports a notice while not open", () => {
    const { client } = setup();
    const notices: string[] = [];
    client.onNotice((notice) => notices.push(notice));

    expect(client.send({ type: "chat", content: "hi" })).toBe(false);
    expect(notices).toHaveLength(1);
  });

  it("delivers parsed frames and drops unreadable ones without throwing", () => {
    const { client, sockets } = setup();
    const frames: ParsedFrame[] = [];
    const notices: string[] = [];
    client.onMessage((frame) => frames.push(frame));
    client.onNotice((notice) => notices.push(notice));

    client.connect();
    sockets[0].open();
    expect(() => {
      sockets[0].deliver("this is not json");
      sockets[0].deliver(undefined);
      sockets[0].deliver(JSON.stringify({ event: "tool_result" }));
      sockets[0].deliver(
        JSON.stringify({
          event: "assistant_delta",
          timestamp: "t",
          session_id: "s",
          payload: { text: "hi" },
        }),
      );
    }).not.toThrow();

    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({ kind: "event", event: "assistant_delta" });
    expect(notices).toHaveLength(3);
  });

  it("reconnects with backoff after an unexpected close, and not after an explicit close", () => {
    const first = setup();
    first.client.connect();
    first.sockets[0].open();
    first.sockets[0].serverClose();
    expect(first.client.getStatus()).toBe("disconnected");
    vi.advanceTimersByTime(10);
    expect(first.sockets).toHaveLength(2);

    const second = setup();
    second.client.connect();
    second.sockets[0].open();
    second.client.close();
    expect(second.sockets[0].closed).toBe(true);
    vi.advanceTimersByTime(1000);
    expect(second.sockets).toHaveLength(1);
  });
});
