import { describe, expect, it } from "vitest";

import { applyFrame, buildTimelineItems, emptyTimeline, foldEvents } from "./events";
import { eventFrame, messageFrame } from "../test/fakeClient";
import type { JsonValue } from "../api/schema";
import type { EventRecord } from "../types/ui";

function record(
  seq: number,
  event: EventRecord["event"],
  payload: Record<string, JsonValue>,
): EventRecord {
  return {
    seq,
    event,
    timestamp: "2024-01-01T00:00:0" + seq + "Z",
    session_id: "s1",
    payload,
    received_at: "2024-01-01T00:00:00Z",
  };
}

describe("applyFrame", () => {
  it("accumulates assistant_delta into one streaming message", () => {
    let state = emptyTimeline();
    state = applyFrame(state, eventFrame("assistant_delta", { text: "Hel" }));
    state = applyFrame(state, eventFrame("assistant_delta", { text: "lo " }));
    state = applyFrame(state, eventFrame("assistant_delta", { text: "world" }));

    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].content).toBe("Hello world");
    expect(state.messages[0].role).toBe("assistant");
    expect(state.messages[0].streaming).toBe(true);
    expect(state.running).toBe(true);
  });

  it("pairs tool_call and tool_result by call_id into a single record", () => {
    let state = emptyTimeline();
    state = applyFrame(
      state,
      eventFrame("tool_call", {
        call_id: "c1",
        tool: "run_shell",
        arguments: { command: "ls" },
        risk: "high",
      }),
    );
    expect(state.toolCalls).toHaveLength(1);
    expect(state.toolCalls[0].status).toBe("running");
    expect(state.toolCalls[0].duration_ms).toBeNull();

    state = applyFrame(
      state,
      eventFrame("tool_result", {
        call_id: "c1",
        tool: "run_shell",
        ok: true,
        duration_ms: 1234,
        risk: "high",
        summary: "listed 3 files",
      }),
    );

    expect(state.toolCalls).toHaveLength(1);
    expect(state.toolCalls[0]).toMatchObject({
      call_id: "c1",
      tool: "run_shell",
      status: "ok",
      duration_ms: 1234,
      risk: "high",
      summary: "listed 3 files",
      ok: true,
    });
  });

  it("keeps a tool_result that arrives without its tool_call", () => {
    const state = applyFrame(
      emptyTimeline(),
      eventFrame("tool_result", {
        call_id: "orphan",
        tool: "read_file",
        ok: false,
        error_code: "not_found",
      }),
    );
    expect(state.toolCalls).toHaveLength(1);
    expect(state.toolCalls[0].status).toBe("failed");
    expect(state.toolCalls[0].error_code).toBe("not_found");
  });

  it("reads a confirm_request that uses the backend's 'id' spelling", () => {
    const state = applyFrame(
      emptyTimeline(),
      eventFrame("confirm_request", {
        id: "req-9",
        tool: "run_shell",
        risk: "high",
        command: "rm -rf build",
        cwd: "/p",
        impact: ["deletes build"],
        reasons: ["destructive"],
        choices: ["reject", "once", "session"],
      }),
    );
    expect(state.confirmations).toHaveLength(1);
    expect(state.confirmations[0]).toMatchObject({
      request_id: "req-9",
      tool: "run_shell",
      risk: "high",
      command: "rm -rf build",
      cwd: "/p",
      impact: ["deletes build"],
    });
    expect(state.confirmations[0].answered_with).toBeNull();
  });

  it("applies state_update, memory_update and done", () => {
    let state = emptyTimeline();
    state = applyFrame(state, eventFrame("assistant_delta", { text: "hi" }));
    state = applyFrame(state, eventFrame("state_update", { project_state: { current_task: "T" } }));
    state = applyFrame(state, eventFrame("memory_update", { memories: [{ key: "k" }] }));
    state = applyFrame(
      state,
      eventFrame("done", { status: "completed", reason: "", steps: 3, tool_calls: 2 }),
    );

    expect(state.projectState).toMatchObject({ current_task: "T" });
    expect(state.memory).toHaveLength(1);
    expect(state.messages[0].streaming).toBe(false);
    expect(state.running).toBe(false);
    expect(state.runStatus).toBe("completed");
  });

  it("records M0 message and error frames", () => {
    let state = applyFrame(emptyTimeline(), messageFrame("m1", "user", "hello"));
    state = applyFrame(state, { kind: "error", error: { code: "invalid_frame", message: "bad" } });
    expect(state.messages).toHaveLength(1);
    expect(state.notices[0]).toContain("invalid_frame");
  });
});

describe("replay", () => {
  const recorded: EventRecord[] = [
    record(1, "assistant_delta", { text: "step one " }),
    record(2, "tool_call", { call_id: "c1", tool: "read_file", risk: "low" }),
    record(3, "tool_result", {
      call_id: "c1",
      tool: "read_file",
      ok: true,
      duration_ms: 10,
      summary: "ok",
    }),
    record(4, "assistant_delta", { text: "step two" }),
  ];

  it("folds the recorded sequence up to an index", () => {
    const atStart = foldEvents(recorded, 0);
    expect(atStart.messages.map((m) => m.content)).toEqual(["step one "]);
    expect(atStart.toolCalls).toHaveLength(0);

    const afterTool = foldEvents(recorded, 2);
    expect(afterTool.toolCalls).toHaveLength(1);
    expect(afterTool.toolCalls[0].status).toBe("ok");
    expect(afterTool.messages).toHaveLength(1);

    const full = foldEvents(recorded);
    expect(full.messages.map((m) => m.content)).toEqual(["step one ", "step two"]);
    expect(full.toolCalls).toHaveLength(1);
  });

  it("renders the replayed sequence as timeline items in order", () => {
    const items = buildTimelineItems(foldEvents(recorded, 2));
    expect(items.map((item) => item.kind)).toEqual(["message", "tool"]);
  });
});
