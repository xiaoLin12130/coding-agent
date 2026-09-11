import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./ChatPanel";
import { resetAppStore, setChatClient, useAppStore } from "../../store/useAppStore";
import { mockApi } from "../../test/apiMock";
import { FakeChatClient } from "../../test/fakeClient";

let client: FakeChatClient;

beforeEach(() => {
  resetAppStore();
  client = new FakeChatClient();
  setChatClient(client);
  mockApi();
  useAppStore.getState().connect();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("ChatPanel", () => {
  it("sends a run frame from the composer", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "refactor the safety layer{Enter}");

    await waitFor(() =>
      expect(client.sent).toContainEqual({
        type: "run",
        task: "refactor the safety layer",
        mode: "single",
      }),
    );
    expect(screen.getByTestId("message-user")).toHaveTextContent("refactor the safety layer");
  });

  it("sends a chat frame when the echo mode is selected", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    await user.click(screen.getByTestId("composer-mode-chat"));
    await user.type(screen.getByLabelText("Message"), "ping{Enter}");

    await waitFor(() => expect(client.sent).toContainEqual({ type: "chat", content: "ping" }));
  });

  it("accumulates assistant_delta frames into one streaming message", async () => {
    render(<ChatPanel />);

    act(() => {
      client.emitEvent("assistant_delta", { text: "Reading " });
      client.emitEvent("assistant_delta", { text: "the " });
      client.emitEvent("assistant_delta", { text: "files…" });
    });

    const messages = await screen.findAllByTestId("message-assistant");
    expect(messages).toHaveLength(1);
    expect(messages[0]).toHaveTextContent("Reading the files…");
    expect(screen.getByTestId("streaming-cursor")).toBeInTheDocument();
  });

  it("renders markdown and highlighted code from a message", async () => {
    render(<ChatPanel />);

    act(() => {
      client.emitEvent("assistant_delta", {
        text: "# Title\n\n- item\n\n```ts\nconst x: number = 1;\n```\n",
      });
    });

    expect(await screen.findByTestId("markdown")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByTestId("code-block")).toBeInTheDocument();
    expect(screen.getAllByTestId("copy-button").length).toBeGreaterThan(0);
  });

  it("renders one tool card for a tool_call / tool_result pair, with risk and duration", async () => {
    render(<ChatPanel />);

    act(() => {
      client.emitEvent("tool_call", {
        call_id: "c1",
        tool: "run_shell",
        arguments: { command: "pytest -q" },
        risk: "high",
      });
    });

    const cards = await screen.findAllByTestId("tool-card");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveAttribute("data-status", "running");
    expect(cards[0]).toHaveTextContent("—");

    act(() => {
      client.emitEvent("tool_result", {
        call_id: "c1",
        tool: "run_shell",
        ok: true,
        duration_ms: 2500,
        risk: "high",
        summary: "42 passed",
      });
    });

    const after = await screen.findAllByTestId("tool-card");
    expect(after).toHaveLength(1);
    expect(after[0]).toHaveAttribute("data-status", "ok");
    expect(after[0]).toHaveTextContent("2.5 s");
    expect(after[0]).toHaveTextContent("risk: high");
    expect(after[0]).toHaveTextContent("42 passed");

    // parameters are visible without expanding the card
    expect(screen.getByTestId("tool-card-params")).toHaveTextContent("command=pytest -q");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getAllByText(/pytest -q/).length).toBeGreaterThan(0);
  });

  it("renders a unified diff that travelled with a tool result", async () => {
    render(<ChatPanel />);

    act(() => {
      client.emitEvent("tool_call", {
        call_id: "c2",
        tool: "write_file",
        arguments: { path: "src/a.ts" },
        risk: "medium",
      });
      client.emitEvent("tool_result", {
        call_id: "c2",
        tool: "write_file",
        ok: true,
        duration_ms: 12,
        risk: "medium",
        summary: "wrote 2 lines",
        diff: "--- a/src/a.ts\n+++ b/src/a.ts\n@@ -1,1 +1,2 @@\n const a = 1;\n+const b = 2;\n",
      });
    });

    const diff = await screen.findByTestId("diff-view");
    expect(diff).toHaveTextContent("const a = 1;");
    expect(diff).toHaveTextContent("+const b = 2;");
    expect(diff).toHaveTextContent("+1");
  });

  it("renders the three confirmation buttons and sends the chosen value", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    act(() => {
      client.emitEvent("confirm_request", {
        request_id: "req-7",
        tool: "run_shell",
        risk: "high",
        command: "rm -rf build",
        cwd: "/h/AI-game/coding-agent",
        impact: ["deletes the build directory"],
        reasons: ["destructive command"],
        choices: ["reject", "once", "session"],
      });
    });

    const reject = await screen.findByTestId("confirm-reject");
    const once = screen.getByTestId("confirm-once");
    const session = screen.getByTestId("confirm-session");

    expect(reject).toHaveTextContent("拒绝");
    expect(once).toHaveTextContent("仅本次");
    expect(session).toHaveTextContent("本会话允许");
    expect(reject).toHaveAttribute("data-choice", "reject");
    expect(once).toHaveAttribute("data-choice", "once");
    expect(session).toHaveAttribute("data-choice", "session");

    expect(screen.getByTestId("confirm-command")).toHaveTextContent("rm -rf build");
    expect(screen.getByTestId("confirm-cwd")).toHaveTextContent("/h/AI-game/coding-agent");
    expect(screen.getByTestId("confirm-risk")).toHaveTextContent("high");
    expect(screen.getByTestId("confirm-impact")).toHaveTextContent("deletes the build directory");

    await user.click(session);

    await waitFor(() =>
      expect(client.sent).toContainEqual({
        type: "confirm",
        request_id: "req-7",
        choice: "session",
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("confirm-card")).toHaveAttribute("data-answered", "session"),
    );
  });

  it("sends the reject choice when 拒绝 is pressed", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    act(() => {
      client.emitEvent("confirm_request", { request_id: "req-8", tool: "write_file", risk: "medium" });
    });

    await user.click(await screen.findByTestId("confirm-reject"));

    await waitFor(() =>
      expect(client.sent).toContainEqual({
        type: "confirm",
        request_id: "req-8",
        choice: "reject",
      }),
    );
  });

  it("stops a running run from the composer", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    act(() => {
      client.emitEvent("assistant_delta", { text: "working" });
    });

    await user.click(await screen.findByTestId("stop-run"));
    await waitFor(() => expect(client.sent.some((frame) => frame.type === "stop")).toBe(true));
  });

  it("retries a user message as a new run", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "first attempt{Enter}");
    await waitFor(() => expect(client.sent).toHaveLength(1));

    await user.click(await screen.findByTestId("message-retry"));

    await waitFor(() => expect(client.sent).toHaveLength(2));
    expect(client.sent[1]).toEqual({ type: "run", task: "first attempt", mode: "single" });
  });

  it("loads a user message into the composer when Edit is used", async () => {
    render(<ChatPanel />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "edit me{Enter}");
    await user.click(await screen.findByTestId("message-edit"));

    expect(screen.getByLabelText("Message")).toHaveValue("edit me");
  });

  it("surfaces a protocol error frame as a notice without crashing", async () => {
    render(<ChatPanel />);

    act(() => {
      client.emit({ kind: "error", error: { code: "invalid_frame", message: "Unsupported frame." } });
    });

    expect(await screen.findByTestId("system-notice")).toHaveTextContent("invalid_frame");
  });
});
