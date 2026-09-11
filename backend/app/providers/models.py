"""Provider descriptions (M9).

A provider is HOW the agent reaches a model. The AgentLoop only ever sees a
ModelClient (app.agents.llm), so a new provider is a new adapter plus a
registry entry - never a change to the loop.

The description below is what the console, the CLI and the evaluation harness
read, so a provider says for itself whether it needs a browser login, a
network connection or a script file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# browser - drives a web LLM through Playwright (M1)
# api     - talks to an HTTP model endpoint
# offline - deterministic, no network at all (tests, evaluation, replay)
ProviderKind = Literal["browser", "api", "offline"]


class ProviderOption(BaseModel):
    """One configuration key a provider accepts."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    required: bool = False
    default: str = ""
    # A secret is never stored in the settings document: it is read from the
    # environment when the provider is built.
    secret: bool = False


class ProviderInfo(BaseModel):
    """What a provider is, without building it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ProviderKind
    label: str
    description: str = ""
    # What actually answers: a web page, an HTTP model, a script.
    model_label: str = ""
    requires_login: bool = False
    requires_network: bool = False
    options: list[ProviderOption] = Field(default_factory=list)

    def option(self, name: str) -> ProviderOption | None:
        for option in self.options:
            if option.name == name:
                return option
        return None


class ProviderError(RuntimeError):
    """The provider could not be found, configured or reached."""

    code = "provider_error"
