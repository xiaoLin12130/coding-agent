import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetAppStore, setChatClient, useAppStore } from "../store/useAppStore";
import type { ProjectState } from "../types";
import { WorkbenchPanel } from "./WorkbenchPanel";

const PROJECT_STATE: ProjectState = {
  current_milestone: "M0",
  current_task: "T1",
  todos: [{ content: "skeleton", status: "in_progress" }],
  files_changed: ["frontend/src/App.tsx"],
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

function mockStateApi(memories: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/project_state")) return jsonResponse(PROJECT_STATE);
      if (url.endsWith("/api/memory")) return jsonResponse({ memories });
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

async function loadState() {
  render(<WorkbenchPanel />);
  await act(async () => {
    await useAppStore.getState().loadState();
  });
}

beforeEach(() => {
  resetAppStore();
  setChatClient(null);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("WorkbenchPanel", () => {
  it("renders project state read from the backend", async () => {
    mockStateApi([{ key: "k" }]);
    await loadState();

    expect(screen.getByTestId("current-milestone")).toHaveTextContent("M0");
    expect(screen.getByTestId("current-task")).toHaveTextContent("T1");
    expect(screen.getByText("skeleton")).toBeInTheDocument();
    expect(screen.getByText("frontend/src/App.tsx")).toBeInTheDocument();
    expect(screen.getByText("Memory entries").parentElement).toHaveTextContent("1");
  });

  it("shows an offline state when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));
    await loadState();

    await waitFor(() =>
      expect(screen.getByTestId("project-state-offline")).toHaveTextContent(
        "Backend offline",
      ),
    );
    expect(screen.queryByTestId("current-milestone")).not.toBeInTheDocument();
  });

  it("marks panels that belong to later milestones as placeholders", async () => {
    mockStateApi();
    await loadState();

    fireEvent.click(screen.getByRole("button", { name: "Tool Calls" }));

    expect(screen.getByTestId("workbench-placeholder")).toHaveTextContent(
      "Tool layer",
    );
  });
});
