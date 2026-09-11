/**
 * Application store (zustand).
 *
 * Holds the connection status, the chat transcript for the current session,
 * and the Project State / Memory snapshot read from the backend.
 */

import { create } from "zustand";

import { fetchState } from "../lib/api";
import { createChatClient, type ChatClient } from "../lib/ws";
import type {
  ChatMessage,
  ConnectionStatus,
  ProjectState,
  ServerFrame,
  StateStatus,
} from "../types";

let client: ChatClient | null = null;
let wiredClient: ChatClient | null = null;

/** Inject a client (tests); pass null to fall back to the real socket. */
export function setChatClient(next: ChatClient | null): void {
  client = next;
  wiredClient = null;
}

export function getChatClient(): ChatClient {
  if (!client) client = createChatClient();
  return client;
}

function newId(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Math.random().toString(16).slice(2);
  return `${prefix}-${random}`;
}

function toMessage(role: "user" | "assistant", content: string): ChatMessage {
  return {
    id: newId(role),
    role,
    content,
    created_at: new Date().toISOString(),
  };
}

export type AppStore = {
  status: ConnectionStatus;
  messages: ChatMessage[];
  notices: string[];
  projectState: ProjectState | null;
  memoryCount: number | null;
  stateStatus: StateStatus;
  stateError: string | null;
  connect: () => void;
  reconnect: () => void;
  sendChat: (content: string) => boolean;
  loadState: () => Promise<void>;
};

const initialState = {
  status: "disconnected" as ConnectionStatus,
  messages: [] as ChatMessage[],
  notices: [] as string[],
  projectState: null as ProjectState | null,
  memoryCount: null as number | null,
  stateStatus: "idle" as StateStatus,
  stateError: null as string | null,
};

export const useAppStore = create<AppStore>((set) => ({
  ...initialState,

  connect: () => {
    const active = getChatClient();
    if (wiredClient !== active) {
      active.onStatus((status) => set({ status }));
      active.onMessage((frame: ServerFrame) => {
        if (frame.type === "message") {
          set((state) => ({ messages: [...state.messages, frame.message] }));
          return;
        }
        set((state) => ({
          notices: [...state.notices, `${frame.error.code}: ${frame.error.message}`],
        }));
      });
      active.onNotice((notice) =>
        set((state) => ({ notices: [...state.notices, notice] })),
      );
      wiredClient = active;
    }
    active.connect();
  },

  reconnect: () => {
    getChatClient().close();
    set({ status: "connecting" });
    getChatClient().connect();
  },

  sendChat: (content: string) => {
    const text = content.trim();
    if (text === "") return false;
    const sent = getChatClient().send({ type: "chat", content: text });
    if (!sent) return false;
    set((state) => ({ messages: [...state.messages, toMessage("user", text)] }));
    return true;
  },

  loadState: async () => {
    set({ stateStatus: "loading", stateError: null });
    try {
      const snapshot = await fetchState();
      set({
        projectState: snapshot.project_state,
        memoryCount: snapshot.memory.memories.length,
        stateStatus: "ready",
        stateError: null,
      });
    } catch (error) {
      set({
        stateStatus: "error",
        stateError: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },
}));

/** Restore the initial state (tests). */
export function resetAppStore(): void {
  setChatClient(null);
  useAppStore.setState({ ...initialState });
}
