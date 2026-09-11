/** REST helpers for the Workbench panel (see docs/api-protocol.md). */

import type { MemoryFile, ProjectState, StateResponse } from "../types";

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

async function getJson(path: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    throw new Error(`${path} responded with ${response.status}`);
  }
  const body: unknown = await response.json();
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new Error(`${path} returned an unexpected payload`);
  }
  return body as Record<string, unknown>;
}

/** Read the persisted project state and memory through the backend. */
export async function fetchState(signal?: AbortSignal): Promise<StateResponse> {
  const [stateBody, memoryBody] = await Promise.all([
    getJson("/api/project_state", signal),
    getJson("/api/memory", signal),
  ]);

  const memory = memoryBody as Partial<MemoryFile>;
  return {
    project_state: {
      current_milestone: (stateBody.current_milestone as string | null) ?? null,
      current_task: (stateBody.current_task as string | null) ?? null,
      goal: (stateBody.goal as string | null) ?? null,
      todos: Array.isArray(stateBody.todos)
        ? (stateBody.todos as ProjectState["todos"])
        : [],
      files_changed: asArray(stateBody.files_changed).filter(
        (item): item is string => typeof item === "string",
      ),
      tests: asArray(stateBody.tests),
      failures: asArray(stateBody.failures),
      decisions: asArray(stateBody.decisions),
      checkpoint: (stateBody.checkpoint as string | null) ?? null,
    },
    memory: { memories: asArray(memory.memories) },
  };
}
