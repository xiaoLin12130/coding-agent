/**
 * Event reduction.
 *
 * The console never invents data: every message, tool card, confirmation and
 * state snapshot is folded out of the documented event stream
 * (docs/api-protocol.md). The same pure reducer drives live rendering and
 * Replay, so a replay shows exactly the sequence that was recorded.
 */

import type { JsonValue, MemoryEntry, ProjectState, RecoverySnapshot } from "../api/schema";
import type {
  AgentEventName,
  ConfirmChoice,
  EventRecord,
  PendingConfirmation,
  TimelineMessage,
  TimelineState,
  ToolCallRecord,
} from "../types/ui";
import type { ParsedFrame } from "./ws";
import { statusLabel } from "./format";

export function emptyTimeline(): TimelineState {
  return {
    messages: [],
    toolCalls: [],
    confirmations: [],
    projectState: null,
    memory: null,
    recovery: null,
    runStatus: "idle",
    runId: null,
    running: false,
    notices: [],
    nextSeq: 1,
  };
}

// -- defensive readers: the stream is DATA, never trusted blindly -----------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function optStr(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return null;
}

function bool(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  return null;
}

function list(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
}

function choicesOf(value: unknown): ConfirmChoice[] {
  const allowed: ConfirmChoice[] = ["reject", "once", "session"];
  const raw = list(value).filter((item): item is ConfirmChoice =>
    (allowed as string[]).includes(item),
  );
  return raw.length > 0 ? raw : allowed;
}

function jsonArgs(value: unknown): Record<string, JsonValue> {
  return isRecord(value) ? (value as Record<string, JsonValue>) : {};
}

// -- payload extraction -----------------------------------------------------

export type ToolCallFields = {
  call_id: string;
  tool: string;
  args: Record<string, JsonValue>;
  risk: string;
};

/** Reads a tool_call payload, tolerating the fields the backend adds. */
export function readToolCall(
  payload: Record<string, unknown>,
  fallbackId: string,
): ToolCallFields {
  return {
    call_id: str(payload.call_id ?? payload.tool_call_id ?? payload.id, fallbackId),
    tool: str(payload.tool ?? payload.name, "unknown"),
    args: jsonArgs(payload.arguments ?? payload.args ?? payload.params),
    risk: str(payload.risk, "unknown"),
  };
}

/** Reads a tool_result payload; every field is optional by construction. */
export function readToolResult(payload: Record<string, unknown>, fallbackId: string) {
  const summary = str(payload.summary ?? payload.message ?? payload.output, "");
  const rawDiff =
    payload.diff ?? payload.patch ?? payload.unified_diff ?? (payload.data as Record<string, unknown>)?.diff;
  return {
    diff: typeof rawDiff === "string" && rawDiff !== "" ? rawDiff : null,
    call_id: str(payload.call_id ?? payload.tool_call_id ?? payload.id, fallbackId),
    tool: str(payload.tool ?? payload.name, "unknown"),
    ok: bool(payload.ok) ?? true,
    error_code: optStr(payload.error_code ?? payload.error),
    duration_ms: num(payload.duration_ms ?? payload.duration),
    risk: str(payload.risk, "unknown"),
    summary,
  };
}

/** Reads a confirm_request payload (the backend sends either id spelling). */
export function readConfirmRequest(
  payload: Record<string, unknown>,
  fallbackId: string,
  seq: number,
): PendingConfirmation {
  const requestId = str(payload.request_id ?? payload.id, "") || fallbackId;
  return {
    request_id: requestId,
    tool: str(payload.tool, "unknown"),
    risk: str(payload.risk, "unknown"),
    command: str(payload.command, ""),
    cwd: str(payload.cwd, ""),
    impact: list(payload.impact),
    reasons: list(payload.reasons),
    choices: choicesOf(payload.choices),
    args: jsonArgs(payload.arguments),
    created_at: str(payload.created_at, ""),
    answered_with: null,
    seq,
  };
}

const MAX_MESSAGES = 400;
const MAX_TOOL_CALLS = 200;
const MAX_CONFIRMATIONS = 50;
const MAX_NOTICES = 50;

function push<T>(items: T[], item: T, cap: number): T[] {
  const next = [...items, item];
  return next.length > cap ? next.slice(next.length - cap) : next;
}

function withSeq(state: TimelineState): TimelineState {
  return { ...state, nextSeq: state.nextSeq + 1 };
}

// -- the reducer ------------------------------------------------------------

/** Fold one inbound frame into the timeline. Pure; always returns a new state. */
export function applyFrame(state: TimelineState, frame: ParsedFrame): TimelineState {
  if (frame.kind === "message") {
    const message: TimelineMessage = {
      id: frame.message.id,
      role: frame.message.role,
      content: frame.message.content,
      created_at: frame.message.created_at,
      seq: state.nextSeq,
    };
    return withSeq({ ...state, messages: push(state.messages, message, MAX_MESSAGES) });
  }

  if (frame.kind === "error") {
    const notice = frame.error.code + ": " + frame.error.message;
    return withSeq({ ...state, notices: push(state.notices, notice, MAX_NOTICES) });
  }

  const { payload } = frame;
  const seq = state.nextSeq;
  const base = { ...state, nextSeq: seq + 1 };

  /** A tool call/result ends the assistant block that asked for it. */
  const closeStreaming = (messages: TimelineMessage[]): TimelineMessage[] =>
    messages.map((message) => (message.streaming ? { ...message, streaming: false } : message));

  switch (frame.event) {
    case "assistant_delta": {
      const text = str(payload.text ?? payload.message, "");
      if (text === "") return base;
      // reset=true means "this is the authoritative text, not an addition": the
      // provider sends it for a whole captured answer, or when the page replaced
      // the node it was writing into.
      const reset = payload.reset === true;
      const messages = [...state.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant" && last.streaming) {
        messages[messages.length - 1] = { ...last, content: reset ? text : last.content + text };
      } else {
        messages.push({
          id: "assistant-" + seq,
          role: "assistant",
          content: text,
          created_at: frame.timestamp,
          seq,
          streaming: true,
        });
      }
      return { ...base, messages, running: true, runStatus: "running" };
    }

    case "tool_call": {
      const fields = readToolCall(payload, "call-" + seq);
      const existing = state.toolCalls.findIndex((entry) => entry.call_id === fields.call_id);
      const record: ToolCallRecord = {
        call_id: fields.call_id,
        tool: fields.tool,
        args: fields.args,
        risk: fields.risk,
        status: "running",
        started_at: frame.timestamp,
        finished_at: null,
        duration_ms: null,
        ok: null,
        error_code: null,
        summary: "",
        diff: null,
        seq,
      };
      const messages = closeStreaming(state.messages);
      if (existing >= 0) {
        const toolCalls = [...state.toolCalls];
        toolCalls[existing] = { ...toolCalls[existing], ...record, seq: toolCalls[existing].seq };
        return { ...base, messages, toolCalls };
      }
      return { ...base, messages, toolCalls: push(state.toolCalls, record, MAX_TOOL_CALLS) };
    }

    case "tool_result": {
      const result = readToolResult(payload, "call-" + seq);
      const index = state.toolCalls.findIndex((entry) => entry.call_id === result.call_id);
      const status: ToolCallRecord["status"] = result.ok ? "ok" : "failed";
      const closedMessages = closeStreaming(state.messages);
      if (index < 0) {
        // A result without a matching call: still show it, never drop data.
        const orphan: ToolCallRecord = {
          call_id: result.call_id,
          tool: result.tool,
          args: {},
          risk: result.risk,
          status,
          started_at: frame.timestamp,
          finished_at: frame.timestamp,
          duration_ms: result.duration_ms,
          ok: result.ok,
          error_code: result.error_code,
          summary: result.summary,
          diff: result.diff,
          seq,
        };
        return {
          ...base,
          messages: closedMessages,
          toolCalls: push(state.toolCalls, orphan, MAX_TOOL_CALLS),
        };
      }
      const toolCalls = [...state.toolCalls];
      const previous = toolCalls[index];
      toolCalls[index] = {
        ...previous,
        status,
        ok: result.ok,
        error_code: result.error_code,
        duration_ms: result.duration_ms ?? previous.duration_ms,
        risk: result.risk !== "unknown" ? result.risk : previous.risk,
        summary: result.summary !== "" ? result.summary : previous.summary,
        diff: result.diff ?? previous.diff,
        finished_at: frame.timestamp,
      };
      return { ...base, messages: closedMessages, toolCalls };
    }

    case "confirm_request": {
      const request = readConfirmRequest(payload, frame.request_id ?? "confirm-" + seq, seq);
      const messages = push(
        state.messages,
        {
          id: "confirm-" + seq,
          role: "system" as const,
          content:
            "需要确认：" + request.tool + " (" + request.risk + " risk).",
          created_at: frame.timestamp,
          seq,
        },
        MAX_MESSAGES,
      );
      return {
        ...base,
        messages,
        confirmations: push(
          state.confirmations.filter((entry) => entry.request_id !== request.request_id),
          request,
          MAX_CONFIRMATIONS,
        ),
      };
    }

    case "state_update": {
      const projectState = isRecord(payload.project_state)
        ? (payload.project_state as unknown as ProjectState)
        : state.projectState;
      const recovery = isRecord(payload.snapshot)
        ? (payload.snapshot as unknown as RecoverySnapshot)
        : state.recovery;
      return { ...base, projectState, recovery };
    }

    case "memory_update": {
      const memories = Array.isArray(payload.memories)
        ? (payload.memories as unknown as MemoryEntry[])
        : state.memory;
      return { ...base, memory: memories };
    }

    case "agent_update": {
      const status = str(payload.status, state.runStatus);
      const runId = optStr(payload.run_id) ?? state.runId;
      const running = !["done", "finished", "idle", "stopped", "failed", "error"].includes(status);
      return { ...base, runStatus: status, runId, running };
    }

    case "error": {
      const notice = str(payload.code, "error") + ": " + str(payload.message, "未指定的错误。");
      return { ...base, notices: push(state.notices, notice, MAX_NOTICES) };
    }

    case "done": {
      const messages = state.messages.map((message) =>
        message.streaming ? { ...message, streaming: false } : message,
      );
      const status = str(payload.status, "done");
      const reason = str(payload.reason, "");
      const notice =
        reason === ""
          ? "运行 " + statusLabel(status)
          : "运行 " + statusLabel(status) + "：" + reason;
      return {
        ...base,
        messages,
        running: false,
        runStatus: status,
        notices: push(state.notices, notice, MAX_NOTICES),
      };
    }

    default:
      return base;
  }
}

/** Fold one recorded event (used by Replay). */
export function applyEvent(state: TimelineState, record: EventRecord): TimelineState {
  const frame: ParsedFrame = {
    kind: "event",
    event: record.event,
    timestamp: record.timestamp,
    session_id: record.session_id,
    payload: record.payload,
  };
  return applyFrame(state, frame);
}

/**
 * Rebuild the timeline from the recorded events up to (and including) `upto`.
 * The default folds the whole recording; `upto` < 0 means "nothing replayed
 * yet", which is where a replay starts before its first step.
 */
export function foldEvents(
  records: EventRecord[],
  upto: number = records.length - 1,
  initial: TimelineState = emptyTimeline(),
): TimelineState {
  if (upto < 0) return initial;
  return records.slice(0, upto + 1).reduce((state, record) => applyEvent(state, record), initial);
}

export type TimelineItem =
  | { kind: "message"; seq: number; message: TimelineMessage }
  | { kind: "tool"; seq: number; tool: ToolCallRecord }
  | { kind: "confirmation"; seq: number; confirmation: PendingConfirmation };

/** Messages, tool cards and confirmations in the order they happened. */
export function buildTimelineItems(state: TimelineState): TimelineItem[] {
  const items: TimelineItem[] = [
    ...state.messages.map((message): TimelineItem => ({ kind: "message", seq: message.seq, message })),
    ...state.toolCalls.map((tool): TimelineItem => ({ kind: "tool", seq: tool.seq, tool })),
    ...state.confirmations.map(
      (confirmation): TimelineItem => ({ kind: "confirmation", seq: confirmation.seq, confirmation }),
    ),
  ];
  return items.sort((left, right) => left.seq - right.seq);
}

/** Confirmations still waiting for an answer. */
export function awaitingConfirmations(state: TimelineState): PendingConfirmation[] {
  return state.confirmations.filter((entry) => entry.answered_with === null);
}

export function eventLabel(record: EventRecord): string {
  const payload = record.payload;
  const message = str(payload.message, "");
  const tool = str(payload.tool, "");
  const parts: string[] = [record.event];
  if (tool !== "") parts.push(tool);
  if (message !== "") parts.push(message);
  return parts.join(" · ");
}

export function isKnownEvent(name: string): name is AgentEventName {
  return (
    name === "assistant_delta" ||
    name === "tool_call" ||
    name === "tool_result" ||
    name === "state_update" ||
    name === "memory_update" ||
    name === "agent_update" ||
    name === "confirm_request" ||
    name === "error" ||
    name === "done"
  );
}
