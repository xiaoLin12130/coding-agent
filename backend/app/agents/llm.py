"""Model clients for the agent loop.

The loop must not care which model answers. Three implementations:

* ScriptedModel  — deterministic output list; drives tests and the acceptance
                   run, and can be resumed from a checkpoint
* CallableModel  — a plain function, for one-off wiring
* BrowserModel   — the real one: it sends the prompt to a web LLM through the
                   M1 ProviderAdapter and captures the reply

The prompt handed to a client is USER content plus untrusted tool results; the
reply is MODEL content and only model content may be parsed as instructions
(see app.safety.check_instruction_source).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable  # noqa: F401

from .models import ModelReply


@runtime_checkable
class ModelClient(Protocol):
    """What the loop needs from a model."""

    name: str

    def complete(self, prompt: str, system: str | None = None) -> ModelReply:
        """Return the model's reply for one prompt."""

    # Optional, used by checkpoints:
    def snapshot(self) -> dict[str, Any]:
        ...

    def restore(self, state: dict[str, Any]) -> None:
        ...


class ModelClientError(RuntimeError):
    """The model could not be reached or returned nothing usable."""

    code = "model_error"


class ScriptedModel:
    """A deterministic model: replies are handed out in order.

    Anything past the end of the script is a plain acknowledgement, so a run
    that should have finished does not hang waiting for a reply that will
    never come.
    """

    name = "scripted"

    def __init__(
        self,
        replies: list[str],
        final_message: str = "Done.",
        name: str = "scripted",
    ) -> None:
        self.replies = list(replies)
        self.final_message = final_message
        self.name = name
        self.index = 0
        self.calls: list[str] = []
        self.exhausted_replies = 0

    def complete(self, prompt: str, system: str | None = None) -> ModelReply:
        self.calls.append(prompt)
        if self.index >= len(self.replies):
            self.exhausted_replies += 1
            return ModelReply(text=self.final_message, source="model")
        reply = self.replies[self.index]
        self.index += 1
        return ModelReply(text=reply, source="model")

    # -- checkpoint support -------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {"index": self.index, "calls": len(self.calls)}

    def restore(self, state: dict[str, Any]) -> None:
        self.index = int(state.get("index", 0))


class CallableModel:
    """Wrap any function as a model."""

    name = "callable"

    def __init__(self, function: Callable[[str, str | None], str], name: str = "callable") -> None:
        self.function = function
        self.name = name
        self.calls: list[str] = []

    def complete(self, prompt: str, system: str | None = None) -> ModelReply:
        self.calls.append(prompt)
        return ModelReply(text=self.function(prompt, system), source="model")

    def snapshot(self) -> dict[str, Any]:
        return {"calls": len(self.calls)}

    def restore(self, state: dict[str, Any]) -> None:  # pragma: no cover - nothing to restore
        return None


class BrowserModel:
    """Drive a web LLM through the M1 browser provider.

    The provider owns sending, completion detection and reply capture; this
    class only adapts it to the ModelClient contract and keeps the captured
    artifacts for the run log.

    Pass 'provider_factory' instead of 'provider' when the page can be
    recovered: a crashed browser is replaced by a NEW provider, and a model
    holding the old one would keep talking to a dead page.
    """

    name = "browser"

    def __init__(
        self,
        provider: Any = None,
        label: str = "browser",
        provider_factory: Callable[[], Any] | None = None,
    ) -> None:
        if provider is None and provider_factory is None:
            raise ValueError("BrowserModel needs a provider or a provider_factory")
        self._provider = provider
        self._provider_factory = provider_factory
        self.name = label
        self.last_reply: Any = None

    @property
    def provider(self) -> Any:
        """The provider to use now: the factory wins when one was supplied."""
        if self._provider_factory is not None:
            return self._provider_factory()
        return self._provider

    def complete(self, prompt: str, system: str | None = None) -> ModelReply:
        text = prompt if not system else system + "\n\n" + prompt
        try:
            reply = self.provider.ask(text)
        except Exception as exc:  # noqa: BLE001 - surfaced as a model error
            raise ModelClientError("the browser provider failed: " + str(exc)) from exc
        self.last_reply = reply
        captured = (reply.text or "").strip()
        if not captured:
            raise ModelClientError("the model returned an empty reply")
        return ModelReply(
            text=captured,
            source="model",
            duration_ms=getattr(reply, "duration_ms", 0),
            meta={
                "completed": getattr(reply, "completed", None),
                "timed_out": getattr(reply, "timed_out", None),
                "capture_source": getattr(reply, "source", None),
                "run_dir": getattr(getattr(reply, "artifacts", None), "run_dir", None),
            },
        )

    def snapshot(self) -> dict[str, Any]:
        return {}

    def restore(self, state: dict[str, Any]) -> None:  # pragma: no cover - nothing to restore
        return None
