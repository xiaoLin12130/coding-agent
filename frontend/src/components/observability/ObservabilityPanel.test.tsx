import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ObservabilityPanel } from "./ObservabilityPanel";
import { resetAppStore, setChatClient, useAppStore } from "../../store/useAppStore";
import { mockApi } from "../../test/apiMock";
import { FakeChatClient } from "../../test/fakeClient";

let client: FakeChatClient;
let api: ReturnType<typeof mockApi>;

beforeEach(async () => {
  resetAppStore();
  client = new FakeChatClient();
  setChatClient(client);
  api = mockApi();
  useAppStore.getState().connect();
  await useAppStore.getState().loadArtifacts();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("ObservabilityPanel", () => {
  it("renders the artifact list from /api/observability/artifacts", async () => {
    render(<ObservabilityPanel />);

    const runs = await screen.findAllByTestId("artifact-run");
    expect(runs).toHaveLength(1);
    expect(runs[0]).toHaveAttribute("data-run-dir", "/tmp/runs/run-1");
    expect(runs[0]).toHaveTextContent("run-1");

    const screenshot = screen.getByTestId("artifact-screenshot");
    expect(screenshot.getAttribute("src")).toContain("/api/observability/file?path=");
    expect(decodeURIComponent(screenshot.getAttribute("src")!)).toContain("/tmp/runs/run-1/step-1.png");

    expect(screen.getAllByTestId("dom-snapshot")).toHaveLength(1);
    expect(screen.getByTestId("artifact-logs")).toHaveTextContent("log.json");
  });

  it("loads a DOM snapshot's text on demand", async () => {
    render(<ObservabilityPanel />);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("dom-snapshot"));

    await waitFor(() =>
      expect(screen.getByTestId("dom-snapshot-text")).toHaveTextContent("<html>dom</html>"),
    );
    expect(api.calls.some((call) => call.url.includes("/api/observability/file"))).toBe(true);
  });

  it("lists the tool history and the event history from the stream", async () => {
    render(<ObservabilityPanel />);

    act(() => {
      client.emitEvent("tool_call", { call_id: "c1", tool: "read_file", risk: "low" });
      client.emitEvent("tool_result", {
        call_id: "c1",
        tool: "read_file",
        ok: true,
        duration_ms: 15,
        summary: "read 10 lines",
      });
    });

    expect(await screen.findByTestId("tool-history")).toHaveTextContent("read_file");
    expect(screen.getByTestId("tool-history")).toHaveTextContent("15 ms");
    expect(screen.getAllByTestId("observed-event")).toHaveLength(2);
  });

  it("re-renders the recorded event sequence when replaying", async () => {
    render(<ObservabilityPanel />);
    const user = userEvent.setup();

    act(() => {
      client.emitEvent("assistant_delta", { text: "one " });
      client.emitEvent("tool_call", { call_id: "c1", tool: "read_file", risk: "low" });
      client.emitEvent("tool_result", { call_id: "c1", tool: "read_file", ok: true, duration_ms: 5 });
    });

    expect(screen.getByTestId("replay-status")).toHaveTextContent("实时");

    await user.click(screen.getByTestId("replay-reset"));
    expect(screen.getByTestId("replay-status")).toHaveTextContent("回放 #3");
    expect(screen.getByTestId("replay-summary")).toHaveTextContent("工具卡片 1");

    await user.click(screen.getByTestId("replay-prev"));
    expect(screen.getByTestId("replay-status")).toHaveTextContent("回放 #2");

    await user.click(screen.getByTestId("replay-prev"));
    expect(screen.getByTestId("replay-summary")).toHaveTextContent("工具卡片 0");

    expect(useAppStore.getState().replay.view.messages[0].content).toBe("one ");

    await user.click(screen.getByTestId("replay-prev"));
    await user.click(screen.getByTestId("replay-prev"));
    expect(screen.getByTestId("replay-summary")).toHaveTextContent("回放消息 0");

    await user.click(screen.getByTestId("replay-stop"));
    expect(screen.getByTestId("replay-status")).toHaveTextContent("实时");
  });
});
