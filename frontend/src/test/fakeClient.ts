import type { ChatClient } from "../lib/ws";
import type { ClientFrame, ConnectionStatus, ServerFrame } from "../types";

/** In-memory ChatClient so tests never open a real socket. */
export class FakeChatClient implements ChatClient {
  sent: ClientFrame[] = [];
  status: ConnectionStatus = "disconnected";

  private messageHandlers = new Set<(frame: ServerFrame) => void>();
  private statusHandlers = new Set<(status: ConnectionStatus) => void>();
  private noticeHandlers = new Set<(notice: string) => void>();

  connect(): void {
    this.setStatus("connected");
  }

  close(): void {
    this.setStatus("disconnected");
  }

  send(frame: ClientFrame): boolean {
    if (this.status !== "connected") return false;
    this.sent.push(frame);
    return true;
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  onMessage(handler: (frame: ServerFrame) => void): () => void {
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

  /** Test hook: push a server frame as if it arrived on the socket. */
  emit(frame: ServerFrame): void {
    this.messageHandlers.forEach((handler) => handler(frame));
  }

  emitNotice(notice: string): void {
    this.noticeHandlers.forEach((handler) => handler(notice));
  }

  private setStatus(next: ConnectionStatus): void {
    this.status = next;
    this.statusHandlers.forEach((handler) => handler(next));
  }
}

export function assistantFrame(id: string, content: string): ServerFrame {
  return {
    type: "message",
    message: {
      id,
      role: "assistant",
      content,
      created_at: new Date().toISOString(),
    },
  };
}
