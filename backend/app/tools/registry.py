"""ToolRegistry: the catalogue of tools that exist, and their contracts.

The registry knows names, schemas and risk levels — never how to run anything.
Execution belongs to the Executor, which is the single real entry point.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from pydantic import BaseModel

from .errors import ToolNotFoundError
from .models import RiskLevel, ToolSpec

ToolHandler = Callable[..., Any]


class RegisteredTool(BaseModel):
    """A spec plus its argument model and handler."""

    model_config = {"arbitrary_types_allowed": True}

    spec: ToolSpec
    args_model: type[BaseModel]
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.spec.name


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    # -- registration ------------------------------------------------------

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError("tool already registered: " + tool.name)
        self._tools[tool.name] = tool

    def tool(
        self,
        name: str,
        description: str,
        args_model: type[BaseModel],
        risk: RiskLevel = "low",
        requires_confirmation: bool = False,
        idempotent: bool = False,
    ):
        """Decorator form used by the built-in module."""

        def decorator(handler: ToolHandler) -> ToolHandler:
            self.register(
                RegisteredTool(
                    spec=ToolSpec(
                        name=name,
                        description=description,
                        risk=risk,
                        requires_confirmation=requires_confirmation,
                        idempotent=idempotent,
                        parameters=args_model.model_json_schema(),
                    ),
                    args_model=args_model,
                    handler=handler,
                )
            )
            return handler

        return decorator

    # -- lookup ------------------------------------------------------------

    def get(self, name: str) -> RegisteredTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError("unknown tool " + repr(name))
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """A registry holding only the named tools.

        This is how a role is restricted: a Planner given this subset has no
        write tool registered at all, so it cannot modify a file even if the
        model asks for one. Restriction by capability, not by instruction.
        """
        wanted = list(names)
        missing = [name for name in wanted if name not in self._tools]
        if missing:
            raise ToolNotFoundError(
                "unknown tool(s) for this role: " + ", ".join(sorted(missing))
            )
        scoped = ToolRegistry()
        for name in wanted:
            scoped.register(self._tools[name])
        return scoped

    def specs(self) -> list[ToolSpec]:
        return [self._tools[name].spec for name in self.names()]

    def schemas(self) -> list[dict]:
        """The catalogue in the shape a model prompt expects."""
        return [
            {
                "name": tool.spec.name,
                "description": tool.spec.description,
                "risk": tool.spec.risk,
                "requires_confirmation": tool.spec.requires_confirmation,
                "parameters": tool.spec.parameters,
            }
            for tool in (self._tools[name] for name in self.names())
        ]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools
