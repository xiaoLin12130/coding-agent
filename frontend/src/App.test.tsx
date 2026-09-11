import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { resetAppStore, setChatClient, useAppStore } from "./store/useAppStore";
import { mockApi } from "./test/apiMock";
import { FakeChatClient } from "./test/fakeClient";

let client: FakeChatClient;
let api: ReturnType<typeof mockApi>;

async function renderApp() {
  render(<App />);
  await screen.findByTestId("app-shell");
}

beforeEach(() => {
  resetAppStore();
  client = new FakeChatClient();
  setChatClient(client);
  api = mockApi();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("app shell", () => {
  it("renders the three column workbench shell", async () => {
    await renderApp();

    expect(screen.getByTestId("panel-sessions")).toBeInTheDocument();
    expect(screen.getByTestId("panel-chat")).toBeInTheDocument();
    expect(screen.getByTestId("panel-workbench")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sessions" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workbench" })).toBeInTheDocument();
  });

  it("reports the backend as online and shows the provider", async () => {
    await renderApp();

    await waitFor(() =>
      expect(screen.getByTestId("backend-status")).toHaveAttribute("data-backend", "online"),
    );
    await waitFor(() => expect(screen.getByTestId("provider-name")).toHaveTextContent("mock"));
    expect(screen.getByTestId("connection-badge")).toHaveAttribute("data-status", "connected");
  });

  it("shows an explicit backend offline state instead of fake data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));
    await renderApp();

    await waitFor(() =>
      expect(screen.getByTestId("backend-status")).toHaveAttribute("data-backend", "offline"),
    );
    const offline = screen.getAllByTestId("backend-offline");
    expect(offline.length).toBeGreaterThan(0);
    expect(offline[0]).toHaveTextContent("Backend offline");
    // no invented sessions or messages
    expect(screen.queryAllByTestId("session-item")).toHaveLength(0);
    expect(screen.queryAllByTestId("message-assistant")).toHaveLength(0);
  });

  it("lists sessions from /api/sessions and loads messages when switching", async () => {
    await renderApp();

    const items = await screen.findAllByTestId("session-item");
    expect(items).toHaveLength(1);
    const list = screen.getByTestId("session-list");
    expect(within(list).getByText("First session")).toBeInTheDocument();
    expect(
      api.calls.filter((call) => call.url.includes("/api/sessions")).length,
    ).toBeGreaterThan(0);

    await waitFor(() => expect(screen.getByText("hello from session one")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId("show-archived"));
    const all = await screen.findAllByTestId("session-item");
    expect(all).toHaveLength(2);
    expect(within(list).getByText("Second session")).toBeInTheDocument();

    await user.click(within(list).getByText("Second session"));

    await waitFor(() =>
      expect(screen.getByText("hello from session two")).toBeInTheDocument(),
    );
    expect(useAppStore.getState().activeSessionId).toBe("session-2");
    expect(
      api.calls.some((call) => call.url.includes("session_id=session-2")),
    ).toBe(true);
  });

  it("opens the settings tab from the session panel", async () => {
    await renderApp();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("open-settings"));
    expect(await screen.findByTestId("settings-panel")).toBeInTheDocument();
  });

  it("renders a tool card that came from the real event stream", async () => {
    await renderApp();

    act(() => {
      client.emitEvent("tool_call", {
        call_id: "c1",
        tool: "run_shell",
        arguments: { command: "ls" },
        risk: "high",
      });
      client.emitEvent("tool_result", {
        call_id: "c1",
        tool: "run_shell",
        ok: true,
        duration_ms: 1200,
        risk: "high",
        summary: "listed files",
      });
    });

    const card = await screen.findByTestId("tool-card");
    expect(card).toHaveAttribute("data-call-id", "c1");
    expect(card).toHaveTextContent("run_shell");
    expect(card).toHaveTextContent("1.2 s");
    expect(card).toHaveTextContent("risk: high");
    expect(card).toHaveTextContent("listed files");
  });
});
