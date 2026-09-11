"""Agent Runtime loop (M5).

    LLM -> ToolCallParser -> SafetyLayer -> Executor -> Tool Result -> Context -> LLM

* models.py     loop limits, events, step records, run result, checkpoint model
* llm.py        ModelClient implementations (scripted, callable, browser)
* checkpoint.py durable run state written after every step
* loop.py       AgentLoop: the loop itself and every bound it respects

Single agent only. Multi-agent orchestration (Planner/Coder/Reviewer/...) is a
later concern; docs/runtime-agents.md requires the single loop to be solid
first.
"""

from .checkpoint import CheckpointStore
from .llm import (
    BrowserModel,
    CallableModel,
    ModelClient,
    ModelClientError,
    ScriptedModel,
)
from .loop import DEFAULT_SYSTEM, AgentLoop, ConfirmationAnswer
from .models import (
    AgentEvent,
    AgentRunResult,
    Checkpoint,
    EventType,
    LoopLimits,
    ModelReply,
    RunStatus,
    StepRecord,
    ToolAttempt,
)

__all__ = [
    "AgentEvent",
    "AgentLoop",
    "AgentRunResult",
    "BrowserModel",
    "CallableModel",
    "Checkpoint",
    "CheckpointStore",
    "ConfirmationAnswer",
    "DEFAULT_SYSTEM",
    "EventType",
    "LoopLimits",
    "ModelClient",
    "ModelClientError",
    "ModelReply",
    "RunStatus",
    "ScriptedModel",
    "StepRecord",
    "ToolAttempt",
]
