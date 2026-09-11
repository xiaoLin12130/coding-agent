import { vi } from "vitest";

/**
 * fetch double for the frozen REST contract.
 *
 * Every test runs against this: no test ever opens a real connection.
 */

export type MockRoutes = Record<string, unknown>;

export type FetchCall = { url: string; method: string; body: unknown };

export const FIXTURES = {
  health: { status: "ok", app: "coding-agent", version: "0.8.0" },
  projectState: {
    current_milestone: "M8",
    current_task: "Frontend workbench",
    goal: "Ship the console",
    todos: [{ content: "tool cards", status: "in_progress" }],
    files_changed: ["frontend/src/App.tsx"],
    tests: ["npm test"],
    failures: [],
    decisions: [],
    checkpoint: "checkpoint-1",
    git_branch: "main",
    cwd: "/h/AI-game/coding-agent",
  },
  memory: {
    memories: [
      {
        key: "stack",
        value: "React 18 + Vite",
        namespace: "project",
        source: "frontend",
        sensitive: false,
        updated_by: "backend",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-02T00:00:00Z",
      },
    ],
  },
  sessions: {
    active_session_id: "session-1",
    recovered: false,
    sessions: [
      {
        id: "session-1",
        title: "First session",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:10:00Z",
        archived: false,
        message_count: 2,
        turn_count: 1,
      },
      {
        id: "session-2",
        title: "Second session",
        created_at: "2025-01-02T00:00:00Z",
        updated_at: "2025-01-02T00:10:00Z",
        archived: true,
        message_count: 5,
        turn_count: 2,
      },
    ],
  },
  messages: {
    "session-1": {
      session_id: "session-1",
      message_count: 2,
      messages: [
        {
          index: 0,
          session_id: "session-1",
          role: "user",
          content: "hello from session one",
          created_at: "2025-01-01T00:00:00Z",
          tool_name: null,
          tool_call_id: null,
          meta: {},
        },
      ],
    },
    "session-2": {
      session_id: "session-2",
      message_count: 1,
      messages: [
        {
          index: 0,
          session_id: "session-2",
          role: "user",
          content: "hello from session two",
          created_at: "2025-01-02T00:00:00Z",
          tool_name: null,
          tool_call_id: null,
          meta: {},
        },
      ],
    },
  },
  settings: {
    provider: { name: "mock", url: "https://example.test/chat", verified: true, notes: "", profiles: ["mock"] },
    browser: { profile_dir: "/tmp/profile", artifacts_dir: "/tmp/runs", headless_allowed: false },
    working_dir: "/h/AI-game/coding-agent",
    safety: {
      project_root: "/h/AI-game/coding-agent",
      extra_roots: [],
      confirm_high_risk: true,
      sensitive_names: [".env"],
    },
    confirmation: { policy: "ask", ttl_seconds: 300 },
    context_thresholds: { soft_ratio: 0.7, hard_ratio: 0.9, soft_recent_turns: 2 },
    multi_agent: {
      enabled: true,
      max_rounds: 3,
      stall_threshold: 2,
      roles: [
        { name: "planner", purpose: "plan", allowed_tools: ["read_file"], max_steps: 4, verdict_kind: "none" },
      ],
    },
  },
  logs: {
    tool_calls: [
      {
        at: "2025-01-01T00:00:00Z",
        call_id: "call-1",
        name: "run_shell",
        arguments_preview: '{"command":"ls"}',
        ok: true,
        duration_ms: 42,
        idempotent_replay: false,
        confirmed: true,
      },
    ],
    events: [
      { type: "run_start", step: 0, at: "2025-01-01T00:00:00Z", message: "started", tool: null, ok: null, data: {} },
    ],
  },
  agents: {
    roles: [
      { name: "coder", purpose: "write code", allowed_tools: ["write_file"], max_steps: 6, verdict_kind: "none" },
    ],
    running: null,
    runs: [
      {
        run_id: "run-1",
        task: "do the thing",
        status: "completed",
        round_count: 1,
        tool_calls: 2,
        duration_ms: 1500,
        at: "2025-01-01T00:00:00Z",
      },
    ],
  },
  artifacts: {
    runs: [
      {
        run_dir: "/tmp/runs/run-1",
        screenshots: ["/tmp/runs/run-1/step-1.png"],
        dom_snapshots: ["/tmp/runs/run-1/step-1.html"],
        logs: ["/tmp/runs/run-1/log.json"],
      },
    ],
  },
  recovery: {
    active_session_id: "session-1",
    session_message_count: 2,
    archived_session_ids: ["session-0"],
    memory_count: 1,
    latest_run: null,
    context_pressure: {
      level: "soft",
      used_chars: 18000,
      budget_chars: 28000,
      ratio: 0.64,
      dropped_sections: ["history_summary"],
    },
    taken_at: "2025-01-01T00:00:00Z",
  },
} as const;

export function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

function textResponse(body: string, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => JSON.parse(body),
    text: async () => body,
  };
}

/**
 * Install a fetch double. `overrides` are matched by substring against the
 * request URL and may be a value, or a function returning a value/Response.
 */
export function mockApi(overrides: Record<string, unknown> = {}) {
  const calls: FetchCall[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = undefined;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    calls.push({ url, method, body });

    for (const [key, value] of Object.entries(overrides)) {
      if (!url.includes(key)) continue;
      const resolved = typeof value === "function" ? (value as (url: string, init?: RequestInit) => unknown)(url, init) : value;
      if (typeof resolved === "string") return textResponse(resolved);
      if (resolved && typeof resolved === "object" && "ok" in (resolved as object)) {
        return resolved as ReturnType<typeof jsonResponse>;
      }
      return jsonResponse(resolved);
    }

    if (url.includes("/api/health")) return jsonResponse(FIXTURES.health);
    if (url.includes("/api/project_state")) return jsonResponse(FIXTURES.projectState);
    if (url.includes("/api/memory")) return jsonResponse(FIXTURES.memory);
    if (url.includes("/api/sessions")) return jsonResponse(FIXTURES.sessions);
    if (url.includes("/api/messages")) {
      const match = /session_id=([^&]+)/.exec(url);
      const sessionId = match ? decodeURIComponent(match[1]) : "session-1";
      const messages = FIXTURES.messages[sessionId as "session-1" | "session-2"];
      return jsonResponse(messages ?? FIXTURES.messages["session-1"]);
    }
    if (url.includes("/api/settings")) {
      // PUT echoes the document, like the backend does.
      if (method === "PUT" && body && typeof body === "object") return jsonResponse(body);
      return jsonResponse(FIXTURES.settings);
    }
    if (url.includes("/api/logs")) return jsonResponse(FIXTURES.logs);
    if (url.includes("/api/agents")) return jsonResponse(FIXTURES.agents);
    if (url.includes("/api/observability/artifacts")) return jsonResponse(FIXTURES.artifacts);
    if (url.includes("/api/observability/file")) return textResponse("<html>dom</html>");
    if (url.includes("/api/recovery")) return jsonResponse(FIXTURES.recovery);
    if (url.includes("/api/agent/run")) return jsonResponse({ run_id: "run-rest", accepted: true });
    if (url.includes("/api/agent/stop")) return jsonResponse({ run_id: "run-rest", stopped: true });
    if (url.includes("/api/agent/confirm")) return jsonResponse({ accepted: true });
    if (url.includes("/api/agent/state")) {
      return jsonResponse({ running: false, run_id: null, status: "idle", task: "", mode: "", events: [] });
    }

    return jsonResponse({ detail: "not mocked: " + url }, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

export function callsTo(calls: FetchCall[], fragment: string): FetchCall[] {
  return calls.filter((call) => call.url.includes(fragment));
}
