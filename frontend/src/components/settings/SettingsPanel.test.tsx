import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPanel } from "./SettingsPanel";
import { resetAppStore, setChatClient, useAppStore } from "../../store/useAppStore";
import { callsTo, jsonResponse, mockApi } from "../../test/apiMock";
import { FakeChatClient } from "../../test/fakeClient";

let client: FakeChatClient;
let api: ReturnType<typeof mockApi>;

beforeEach(async () => {
  resetAppStore();
  client = new FakeChatClient();
  setChatClient(client);
  api = mockApi();
  useAppStore.getState().connect();
  await useAppStore.getState().loadSettings();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetAppStore();
});

describe("SettingsPanel", () => {
  it("renders every settings section from GET /api/settings", () => {
    render(<SettingsPanel />);

    expect(screen.getByTestId("settings-provider-name")).toHaveValue("mock");
    expect(screen.getByTestId("settings-working-dir")).toHaveValue("/h/AI-game/coding-agent");
    expect(screen.getByTestId("settings-policy")).toHaveValue("ask");
    expect(screen.getByTestId("settings-soft-ratio")).toHaveValue(0.7);
    expect(screen.getByTestId("settings-multi-rounds")).toHaveValue(3);
    expect(screen.getByTestId("settings-roles")).toHaveTextContent("planner");
  });

  it("round-trips an edit through PUT /api/settings", async () => {
    render(<SettingsPanel />);
    const user = userEvent.setup();

    const name = screen.getByTestId("settings-provider-name");
    await user.clear(name);
    await user.type(name, "renamed-provider");
    expect(screen.getByTestId("settings-dirty")).toBeInTheDocument();

    await user.click(screen.getByTestId("settings-save"));

    await waitFor(() => expect(screen.getByTestId("settings-saved")).toBeInTheDocument());

    const put = callsTo(api.calls, "/api/settings").find((call) => call.method === "PUT");
    expect(put).toBeDefined();
    expect((put!.body as { provider: { name: string } }).provider.name).toBe("renamed-provider");
    expect(useAppStore.getState().settings.data?.provider.name).toBe("renamed-provider");
    expect(screen.getByTestId("settings-provider-name")).toHaveValue("renamed-provider");
  });

  it("saves the confirmation policy and the context thresholds", async () => {
    render(<SettingsPanel />);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByTestId("settings-policy"), "deny");
    const softRatio = screen.getByTestId("settings-soft-ratio");
    await user.clear(softRatio);
    await user.type(softRatio, "0.5");
    await user.click(screen.getByTestId("settings-save"));

    await waitFor(() => expect(screen.getByTestId("settings-saved")).toBeInTheDocument());

    const put = callsTo(api.calls, "/api/settings").find((call) => call.method === "PUT");
    const body = put!.body as {
      confirmation: { policy: string };
      context_thresholds: { soft_ratio: number };
    };
    expect(body.confirmation.policy).toBe("deny");
    expect(body.context_thresholds.soft_ratio).toBe(0.5);
  });

  it("reports a save failure without pretending it worked", async () => {
    api = mockApi({
      "/api/settings": (_url: string, init?: RequestInit) =>
        init?.method === "PUT"
          ? jsonResponse({ detail: "nope" }, 500)
          : jsonResponse({
              provider: { name: "mock", url: "", verified: true, notes: "", profiles: [] },
              browser: { profile_dir: "/p", artifacts_dir: "/r", headless_allowed: false },
              working_dir: "/w",
              safety: { project_root: "/w", extra_roots: [], confirm_high_risk: true, sensitive_names: [] },
              confirmation: { policy: "ask", ttl_seconds: 300 },
              context_thresholds: { soft_ratio: 0.7, hard_ratio: 0.9, soft_recent_turns: 2 },
              multi_agent: { enabled: true, max_rounds: 3, stall_threshold: 2, roles: [] },
            }),
    });
    render(<SettingsPanel />);
    const user = userEvent.setup();

    await user.click(screen.getByTestId("settings-save"));

    await waitFor(() => expect(screen.getByTestId("settings-error")).toBeInTheDocument());
    expect(screen.queryByTestId("settings-saved")).not.toBeInTheDocument();
  });
});
