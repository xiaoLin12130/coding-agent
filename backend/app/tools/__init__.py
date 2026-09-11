"""Tool layer (M3).

Pipeline: ToolCall -> Parser -> Executor -> Tool Result.

* parser.py    turns raw model output into ToolCall objects (JSON, JSON5,
               code fences, multiple calls, bracket matching) and reports
               structured, repairable errors
* registry.py  the catalogue: names, schemas, risk levels
* builtin.py   the nine tools themselves
* executor.py  the single real entry point: validation, confirmation seam,
               logging, error handling, idempotency

SafetyLayer and the confirmation UI are M4; the Executor only carries the
seam they plug into.
"""

from .builtin import (
    ToolContext,
    ToolOutcome,
    build_default_registry,
    default_registry,
)
from .errors import (
    ConfirmationRequiredError,
    ToolBudgetExceededError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from .executor import Executor, idempotency_key
from .json5 import Json5Error
from .models import (
    CallFormat,
    ParseIssue,
    ParseOutcome,
    RiskLevel,
    ToolCall,
    ToolCallLogEntry,
    ToolErrorInfo,
    ToolResult,
    ToolSpec,
)
from .parser import (
    ParseRetryPolicy,
    parse_tool_calls,
    repair_prompt,
    scan_balanced,
)
from .registry import RegisteredTool, ToolRegistry

__all__ = [
    "CallFormat",
    "ConfirmationRequiredError",
    "Executor",
    "Json5Error",
    "ParseIssue",
    "ParseOutcome",
    "ParseRetryPolicy",
    "RegisteredTool",
    "RiskLevel",
    "ToolBudgetExceededError",
    "ToolCall",
    "ToolCallLogEntry",
    "ToolContext",
    "ToolError",
    "ToolErrorInfo",
    "ToolExecutionError",
    "ToolNotFoundError",
    "ToolOutcome",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolValidationError",
    "build_default_registry",
    "default_registry",
    "idempotency_key",
    "parse_tool_calls",
    "repair_prompt",
    "scan_balanced",
]
