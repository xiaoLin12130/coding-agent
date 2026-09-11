"""An HTTP model provider (M9): any OpenAI-compatible chat endpoint.

This is the proof that the loop is provider-agnostic: the adapter speaks the
common /chat/completions shape, so a deployment can point it at a local
llama.cpp server, a vLLM box or a hosted API, and the AgentLoop is unchanged.

The adapter owns transport concerns only - URL, auth, JSON. It never parses
tool calls: that stays the ToolCallParser's job, downstream of the loop.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx

from ..agents.llm import ModelClientError
from ..agents.models import ModelReply
from .models import ProviderError, ProviderInfo, ProviderOption
from .registry import ProviderRegistry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.llm import ModelClient

INFO = ProviderInfo(
    name="openai_compatible",
    kind="api",
    label="OpenAI-compatible HTTP API",
    description=(
        "POST /chat/completions to any OpenAI-compatible endpoint. Needs network "
        "access; the API key is read from an environment variable and is never "
        "written to the settings document."
    ),
    model_label="a chat-completions endpoint",
    requires_login=False,
    requires_network=True,
    options=[
        ProviderOption(
            name="base_url",
            description="Endpoint root, for example http://127.0.0.1:8080/v1",
            required=True,
        ),
        ProviderOption(name="model", description="Model name sent in the request", required=True),
        ProviderOption(
            name="api_key_env",
            description="Environment variable holding the API key",
            default="OPENAI_API_KEY",
            secret=True,
        ),
        ProviderOption(
            name="api_key",
            description="API key supplied directly (never persisted)",
            secret=True,
        ),
        ProviderOption(name="timeout_s", description="Request timeout in seconds", default="120"),
        ProviderOption(
            name="temperature",
            description="Sampling temperature (omitted when empty)",
        ),
        ProviderOption(
            name="label",
            description="Name shown for this model",
            default="openai_compatible",
        ),
    ],
)


class HttpChatModel:
    """A ModelClient over an OpenAI-compatible HTTP endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 120.0,
        temperature: float | None = None,
        label: str = "openai_compatible",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        root = (base_url or "").strip().rstrip("/")
        if not root:
            raise ProviderError("base_url must not be empty")
        if not (model or "").strip():
            raise ProviderError("model must not be empty")
        self.base_url = root
        self.model_name = model.strip()
        self.api_key = api_key
        self.temperature = temperature
        self.name = label
        self.calls: list[str] = []
        # A transport can be injected so a test never touches the network.
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    # -- ModelClient -------------------------------------------------------

    def complete(self, prompt: str, system: str | None = None) -> ModelReply:
        self.calls.append(prompt)
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {"model": self.model_name, "messages": messages}
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key

        url = self.base_url + "/chat/completions"
        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ModelClientError(
                "the model endpoint could not be reached at " + url + ": " + str(exc)
            ) from exc

        if response.status_code >= 400:
            body = response.text[:300].replace("\n", " ").replace("\r", " ")
            raise ModelClientError(
                "the model endpoint answered " + str(response.status_code) + ": " + body
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelClientError("the model endpoint did not answer JSON") from exc

        text = _first_message_text(data)
        if not text.strip():
            raise ModelClientError("the model endpoint returned an empty reply")
        usage = data.get("usage") if isinstance(data, dict) else None
        return ModelReply(
            text=text,
            source="model",
            meta={
                "provider": self.name,
                "model": self.model_name,
                "usage": usage if isinstance(usage, dict) else {},
            },
        )

    def snapshot(self) -> dict[str, Any]:
        return {}

    def restore(self, state: dict[str, Any]) -> None:  # pragma: no cover - stateless
        return None

    def close(self) -> None:
        self._client.close()


def _first_message_text(data: Any) -> str:
    """Read choices[0].message.content, tolerating the common variants."""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        # Some servers return content as a list of parts.
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
    text = first.get("text")
    return text if isinstance(text, str) else ""


def create(
    base_url: str,
    model: str,
    api_key: str = "",
    api_key_env: str = "OPENAI_API_KEY",
    timeout_s: Any = 120,
    temperature: Any = None,
    label: str = "openai_compatible",
) -> "ModelClient":
    """Build the HTTP model. The key comes from the argument or the environment."""
    key = api_key or (os.environ.get(api_key_env, "") if api_key_env else "")
    try:
        timeout = float(timeout_s)
    except (TypeError, ValueError) as exc:
        raise ProviderError("timeout_s must be a number") from exc
    temp: float | None
    if temperature in (None, ""):
        temp = None
    else:
        try:
            temp = float(temperature)
        except (TypeError, ValueError) as exc:
            raise ProviderError("temperature must be a number") from exc
    return HttpChatModel(
        base_url=base_url,
        model=model,
        api_key=key,
        timeout_s=timeout,
        temperature=temp,
        label=label,
    )


def register(registry: ProviderRegistry) -> None:
    registry.register(INFO, create)
