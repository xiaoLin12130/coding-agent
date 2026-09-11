/**
 * Wire types shared with the backend.
 *
 * Everything arriving from the server or from the state files is DATA:
 * it is parsed defensively and never treated as an instruction.
 */

export type Role = "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  created_at: string;
};

export type TodoItem = {
  content: string;
  status: string;
};

export type ProjectState = {
  current_milestone: string | null;
  current_task: string | null;
  goal?: string | null;
  todos: TodoItem[];
  files_changed: string[];
  tests: unknown[];
  failures: unknown[];
  decisions: unknown[];
  checkpoint: string | null;
};

export type MemoryFile = {
  memories: unknown[];
};

export type StateResponse = {
  project_state: ProjectState;
  memory: MemoryFile;
};

export type ClientFrame = { type: "chat"; content: string };

export type MessageFrame = { type: "message"; message: ChatMessage };

export type ErrorFrame = {
  type: "error";
  error: { code: string; message: string };
};

export type ServerFrame = MessageFrame | ErrorFrame;

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type StateStatus = "idle" | "loading" | "ready" | "error";
