"""The offline provider: a scripted model (M9).

Answers come from a plan file, in order. It exists so a run can be replayed
exactly - that is what the evaluation suite and the regression tests need - and
so the whole stack (parser, safety, executor, loop) can be exercised with no
browser, no network and no model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..agents.llm import ScriptedModel
from .models import ProviderError, ProviderInfo, ProviderOption
from .registry import ProviderRegistry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.llm import ModelClient

INFO = ProviderInfo(
    name="scripted",
    kind="offline",
    label="Scripted (offline)",
    description=(
        "Replay a fixed list of model replies. Deterministic and offline: used by "
        "the CLI, the evaluation suite and the regression tests."
    ),
    model_label="a plan file of canned replies",
    requires_login=False,
    requires_network=False,
    options=[
        ProviderOption(
            name="plan",
            description="Path to a JSON file holding a list of replies, or an object with a 'replies' list",
        ),
        ProviderOption(
            name="final_message",
            description="Reply used once the plan is exhausted",
            default="Done.",
        ),
        ProviderOption(
            name="replies",
            description="Replies supplied inline instead of a plan file",
        ),
        ProviderOption(name="label", description="Name shown for this model", default="scripted"),
    ],
)


def read_plan(path: str | Path) -> list[str]:
    """Load a plan file: a list of replies, or an object with a 'replies' list."""
    file = Path(path)
    if not file.exists():
        raise ProviderError("no such plan file: " + str(file))
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError("the plan file is not valid JSON: " + exc.msg) from exc
    if isinstance(raw, dict):
        replies = raw.get("replies", [])
    elif isinstance(raw, list):
        replies = raw
    else:
        raise ProviderError("the plan file must be a list or an object with 'replies'")
    if not isinstance(replies, list):
        raise ProviderError("'replies' must be a list")
    return [_as_text(item) for item in replies]


def _as_text(item: Any) -> str:
    return item if isinstance(item, str) else json.dumps(item)


def create(
    plan: str = "",
    replies: Any = None,
    final_message: str = "Done.",
    label: str = "scripted",
) -> "ModelClient":
    """Build the scripted model from a plan file or inline replies."""
    items: list[str]
    if plan:
        items = read_plan(plan)
    elif replies is not None:
        if not isinstance(replies, list):
            raise ProviderError("'replies' must be a list of strings")
        items = [_as_text(item) for item in replies]
    else:
        items = []
    return ScriptedModel(items, final_message=final_message, name=label)


def register(registry: ProviderRegistry) -> None:
    registry.register(INFO, create)
