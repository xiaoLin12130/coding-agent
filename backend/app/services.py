"""Chat service.

M0 behaviour is deliberately minimal: the server echoes the user's message
back. No LLM, no Browser, no Tool layer, no AgentLoop exists yet.
"""

from __future__ import annotations

from .models import ChatInbound, ChatMessage, new_message


class ChatService:
    def handle(self, inbound: ChatInbound) -> ChatMessage:
        """Turn one inbound chat frame into the assistant reply frame."""
        content = inbound.content.strip()
        return new_message("assistant", f"Echo: {content}")
