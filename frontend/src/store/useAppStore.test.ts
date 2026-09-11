import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetAppStore, setChatClient, useAppStore } from "./useAppStore";
import { callsTo, jsonResponse, mockApi } from "../test/apiMock";
import { FakeChatClient } from "../test/fakeClient";

let client: FakeChatClient;
let api: ReturnType<typeof mockApi>;

beforeEach(() => {
  resetAppStore();
  client = new FakeChatClient();
  setChatClient(client);
  api = mockApi();
  useAppStore.getState().connect();
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("socket wiring", () => {
  it("connects the injected client and mirrors its status", () => {
    expect(client.getStatus()).toBe("connected");
    expect(useAppStore.getState().connection).toBe("connected");
  });

  it("sends the exact run frame for a task, and echoes the task locally", async () => {
    const accepted = await useAppStore.getState().startRun({ task: "fix the parser", mode: "multi" });

    expect(accepted).toBe(true);
    expect(client.sent).toEqual([{ type: "run", task: "fix the parser", mode: "multi" }]);
    const messages = useAppStore.getState().live.messages;
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ role: "user", content: "fix the parser" });
    expect(useAppStore.getState().live.running).toBe(true);
  });

  it("only includes the optional limits that were requested", async () => {
    await useAppStore.getState().startRun({ task: "t", mode: "single", max_steps: 4, auto_confirm: true });
    expect(client.sent[0]).toEqual({
      type: "run",
      task: "t",
      mode: "single",
      max_steps: 4,
      auto_confirm: true,
    });
  });

  it("sends a chat frame for the M0 echo mode", () => {
    expect(useAppStore.getState().sendChat("hello")).toBe(true);
    expect(client.sent[0]).toEqual({ type: "chat", content: "hello" });
    expect(useAppStore.getState().sendChat("   ")).toBe(false);
  });

  it("sends the confirm frame with the chosen value", () => {
    client.emitEvent("confirm_request", {
      request_id: "req-1",
      tool: "run_shell",
      risk: "high",
      choices: ["reject", "once", "session"],
    });

    useAppStore.getState().respondConfirm("req-1", "session");

    expect(client.sent).toEqual([{ type: "confirm", request_id: "req-1", choice: "session" }]);
    const confirmation = useAppStore.getState().live.confirmations[0];
    expect(confirmation.answered_with).toBe("session");
  });

  it("falls back to POST /api/agent/confirm when the socket is down", async () => {
    client.close();
    client.emitEvent("confirm_request", { request_id: "req-2", tool: "run_shell", risk: "high" });

    useAppStore.getState().respondConfirm("req-2", "once");
    await vi.waitFor(() => {
      expect(callsTo(api.calls, "/api/agent/confirm")).toHaveLength(1);
    });
    expect(callsTo(api.calls, "/api/agent/confirm")[0].body).toEqual({
      request_id: "req-2",
      choice: "once",
    });
  });

  it("stops the run over the socket and over REST", async () => {
    await useAppStore.getState().startRun({ task: "t", mode: "single" });
    await useAppStore.getState().stopRun();

    expect(client.sent.some((frame) => frame.type === "stop")).toBe(true);
    expect(callsTo(api.calls, "/api/agent/stop")).toHaveLength(1);
    expect(useAppStore.getState().live.running).toBe(false);
  });

  it("asks for a recovery snapshot over the socket", () => {
    useAppStore.getState().requestSnapshot();
    expect(client.sent).toEqual([{ type: "snapshot" }]);
  });
});

describe("event stream", () => {
  it("accumulates assistant_delta into a single streaming message", () => {
    client.emitEvent("assistant_delta", { text: "Work" });
    client.emitEvent("assistant_delta", { text: "ing" });
    client.emitEvent("assistant_delta", { text: "…" });

    const messages = useAppStore.getState().live.messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe("Working…");
    expect(messages[0].streaming).toBe(true);
    expect(useAppStore.getState().events).toHaveLength(3);
  });

  it("pairs tool_call with tool_result and keeps the raw event history", () => {
    client.emitEvent("tool_call", { call_id: "c9", tool: "write_file", arguments: { path: "a.ts" }, risk: "medium" });
    client.emitEvent("tool_result", { call_id: "c9", tool: "write_file", ok: false, error_code: "denied", duration_ms: 30, summary: "blocked" });

    const calls = useAppStore.getState().live.toolCalls;
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ status: "failed", error_code: "denied", duration_ms: 30 });

    const events = useAppStore.getState().events;
    expect(events.map((entry) => entry.event)).toEqual(["tool_call", "tool_result"]);
    expect(events[0].seq).toBe(1);
    expect(events[1].seq).toBe(2);
  });

  it("applies state_update and done to the live timeline", () => {
    client.emitEvent("assistant_delta", { text: "done " });
    client.emitEvent("state_update", {
      project_state: { current_milestone: "M8", current_task: "workbench", todos: [], files_changed: [], tests: [], failures: [], decisions: [], checkpoint: null },
    });
    client.emitEvent("done", { status: "completed", reason: "finished", steps: 2, tool_calls: 1 });

    const live = useAppStore.getState().live;
    expect(live.projectState?.current_milestone).toBe("M8");
    expect(live.running).toBe(false);
    expect(live.messages[0].streaming).toBe(false);
  });

  it("replays the recorded events up to an index", () => {
    client.emitEvent("assistant_delta", { text: "one " });
    client.emitEvent("tool_call", { call_id: "c1", tool: "read_file", risk: "low" });
    client.emitEvent("assistant_delta", { text: "two" });

    useAppStore.getState().startReplay();
    expect(useAppStore.getState().replay.active).toBe(true);
    expect(useAppStore.getState().replay.index).toBe(2);

    useAppStore.getState().setReplayIndex(0);
    const view = useAppStore.getState().replay.view;
    expect(view.messages.map((message) => message.content)).toEqual(["one "]);
    expect(view.toolCalls).toHaveLength(0);

    useAppStore.getState().stepReplay(1);
    expect(useAppStore.getState().replay.view.toolCalls).toHaveLength(1);

    useAppStore.getState().stopReplay();
    expect(useAppStore.getState().replay.active).toBe(false);
  });
});

describe("REST resources", () => {
  it("loads sessions, project state, memory and settings", async () => {
    await useAppStore.getState().loadSessions();
    await useAppStore.getState().loadProjectState();
    await useAppStore.getState().loadMemory();
    await useAppStore.getState().loadSettings();

    const state = useAppStore.getState();
    expect(state.sessions.data).toHaveLength(2);
    expect(state.activeSessionId).toBe("session-1");
    expect(state.live.projectState?.current_milestone).toBe("M8");
    expect(state.memory.data?.[0].key).toBe("stack");
    expect(state.settings.data?.provider.name).toBe("mock");
    expect(state.settingsDraft?.provider.name).toBe("mock");
    expect(state.backend).toBe("online");
  });

  it("round-trips a settings change through PUT /api/settings", async () => {
    await useAppStore.getState().loadSettings();
    const draft = useAppStore.getState().settingsDraft;
    expect(draft).not.toBeNull();

    useAppStore.getState().setSettingsDraft({
      ...draft!,
      provider: { ...draft!.provider, name: "renamed" },
      working_dir: "/tmp/work",
    });
    await useAppStore.getState().saveSettings();

    const put = callsTo(api.calls, "/api/settings").find((call) => call.method === "PUT");
    expect(put).toBeDefined();
    expect((put!.body as { provider: { name: string } }).provider.name).toBe("renamed");
    expect((put!.body as { working_dir: string }).working_dir).toBe("/tmp/work");

    const state = useAppStore.getState();
    expect(state.saveStatus).toBe("ready");
    expect(state.settings.data?.provider.name).toBe("renamed");
    expect(state.settingsDraft?.provider.name).toBe("renamed");
  });

  it("marks the backend offline when a request cannot be made", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));

    const online = await useAppStore.getState().checkBackend();
    expect(online).toBe(false);

    await useAppStore.getState().loadSessions();
    await useAppStore.getState().loadSettings();

    const state = useAppStore.getState();
    expect(state.backend).toBe("offline");
    expect(state.backendError).toContain("offline");
    expect(state.sessions.data).toBeNull();
    expect(state.sessions.error).toBeTruthy();
    expect(state.settings.data).toBeNull();
  });

  it("keeps the backend online when an endpoint answers with an HTTP error", async () => {
    api = mockApi({ "/api/memory": jsonResponse({ detail: "boom" }, 500) });
    await useAppStore.getState().checkBackend();
    await useAppStore.getState().loadMemory();

    const state = useAppStore.getState();
    expect(state.backend).toBe("online");
    expect(state.memory.status).toBe("error");
    expect(state.memory.error).toContain("HTTP");
  });

  it("creates a session and switches to it", async () => {
    await useAppStore.getState().newSession("Fresh");
    expect(callsTo(api.calls, "/api/sessions").some((call) => call.method === "POST")).toBe(true);
  });

  it("archives a session", async () => {
    await useAppStore.getState().archiveSession("session-2");
    expect(
      callsTo(api.calls, "/api/sessions/session-2/archive").some((call) => call.method === "POST"),
    ).toBe(true);
  });
});
