import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { resetAppStore, setChatClient } from "./store/useAppStore";
import { FakeChatClient, assistantFrame } from "./test/fakeClient";
import type { ProjectState } from "./types";

const PROJECT_STATE: ProjectState = {
  current_milestone: "M0",
  current_task: "T1",
  todos: [{ content: "skeleton", status: "in_progress" }],
  files_changed: ["backend/app/main.py"],
  tests: [],
  failures: [],
  decisions: [],
  checkpoint: null,
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function mockStateApi(
  projectState: ProjectState = PROJECT_STATE,
  memories: unknown[] = [],
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/project_state")) return jsonResponse(projectState);
    if (url.endsWith("/api/memory")) return jsonResponse({ memories });
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

let client: FakeChatClient;

/** Render the app and wait until the initial state fetch has settled. */
async function renderApp() {
  render(<App />);
  await screen.findByTestId("project-state");
}

beforeEach(() => {
  resetAppStore();
  client = new FakeChatClient();
  setChatClient(client);
});

afterEach(() => {
  // Unmount before touching the store so no component updates outside act().
  cleanup();
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("app shell", () => {
  it("renders the three column skeleton", async () => {
    mockStateApi();
    await renderApp();

    expect(screen.getByTestId("panel-sessions")).toBeInTheDocument();
    expect(screen.getByTestId("panel-chat")).toBeInTheDocument();
    expect(screen.getByTestId("panel-workbench")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sessions" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workbench" })).toBeInTheDocument();
  });

  it("shows the connection status of the socket", async () => {
    mockStateApi();
    await renderApp();

    await waitFor(() =>
      expect(screen.getByTestId("connection-badge")).toHaveAttribute(
        "data-status",
        "connected",
      ),
    );
  });

  it("loads the project state into the workbench", async () => {
    mockStateApi();
    await renderApp();

    await waitFor(() =>
      expect(screen.getByTestId("current-milestone")).toHaveTextContent("M0"),
    );
    expect(screen.getByTestId("current-task")).toHaveTextContent("T1");
  });
});

describe("chat flow", () => {
  it("sends a chat frame and renders the echoed reply", async () => {
    mockStateApi();
    const user = userEvent.setup();
    await renderApp();

    const composer = screen.getByLabelText("Message");
    await user.type(composer, "hello agent{Enter}");

    expect(client.sent).toEqual([{ type: "chat", content: "hello agent" }]);
    expect(screen.getByTestId("message-user")).toHaveTextContent("hello agent");

    act(() => {
      client.emit(assistantFrame("a1", "Echo: hello agent"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("message-assistant")).toHaveTextContent(
        "Echo: hello agent",
      ),
    );
  });

  it("does not send blank input", async () => {
    mockStateApi();
    const user = userEvent.setup();
    await renderApp();

    const composer = screen.getByLabelText("Message");
    await user.type(composer, "   {Enter}");

    expect(client.sent).toEqual([]);
    expect(screen.queryByTestId("message-user")).not.toBeInTheDocument();
  });

  it("surfaces a protocol error frame as a notice", async () => {
    mockStateApi();
    await renderApp();

    act(() => {
      client.emit({
        type: "error",
        error: { code: "invalid_frame", message: "Unsupported frame." },
      });
    });

    await waitFor(() =>
      expect(screen.getByTestId("system-notice")).toHaveTextContent(
        "invalid_frame",
      ),
    );
  });
});
