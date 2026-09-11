import type { ParsedFrame } from "../lib/ws";
import type { ChatClient, ChatClientFrame } from "../lib/ws";
import type { JsonValue } from "../api/schema";
import type { AgentEventName, ChatMessage, ConnectionStatus } from "../types/ui";

/** In-memory ChatClient so tests never open a real socket. */
export class FakeChatClient implements ChatClient {
  sent: ChatClientFrame[] = [];
  status: ConnectionStatus = "disconnected";
  rawSent: string[] = [];

  private messageHandlers = new Set<(frame: ParsedFrame) => void>();
  private statusHandlers = new Set<(status: ConnectionStatus) => void>();
  private noticeHandlers = new Set<(notice: string) => void>();

  connect(): void {
    this.setStatus("connected");
  }

  close(): void {
    this.setStatus("disconnected");
  }

  send(frame: ChatClientFrame): boolean {
    if (this.status !== "connected") return false;
    this.sent.push(frame);
    this.rawSent.push(JSON.stringify(frame));
    return true;
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  onMessage(handler: (frame: ParsedFrame) => void): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatus(handler: (status: ConnectionStatus) => void): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  onNotice(handler: (notice: string) => void): () => void {
    this.noticeHandlers.add(handler);
    return () => this.noticeHandlers.delete(handler);
  }

  /** Test hook: push a parsed frame as if it arrived on the socket. */
  emit(frame: ParsedFrame): void {
    this.messageHandlers.forEach((handler) => handler(frame));
  }

  /** Test hook: push a documented envelope event. */
  emitEvent(
    event: AgentEventName,
    payload: Record<string, JsonValue> = {},
    extra: { request_id?: string; tool_call_id?: string; agent_id?: string } = {},
  ): void {
    this.emit(eventFrame(event, payload, extra));
  }

  /** Test hook: push an M0 message frame. */
  emitMessage(id: string, role: "user" | "assistant", content: string): void {
    this.emit(messageFrame(id, role, content));
  }

  emitNotice(notice: string): void {
    this.noticeHandlers.forEach((handler) => handler(notice));
  }

  private setStatus(next: ConnectionStatus): void {
    this.status = next;
    this.statusHandlers.forEach((handler) => handler(next));
  }
}

export function messageFrame(
  id: string,
  role: "user" | "assistant",
  content: string,
): ParsedFrame {
  const message: ChatMessage = { id, role, content, created_at: new Date().toISOString() };
  return { kind: "message", message };
}

export function eventFrame(
  event: AgentEventName,
  payload: Record<string, JsonValue> = {},
  extra: { request_id?: string; tool_call_id?: string; agent_id?: string } = {},
): ParsedFrame {
  return {
    kind: "event",
    event,
    timestamp: new Date().toISOString(),
    session_id: "session-1",
    payload,
    ...extra,
  };
}
