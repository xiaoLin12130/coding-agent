"""Tool layer errors."""

from __future__ import annotations


class ToolError(RuntimeError):
    """Base class for tool layer failures."""

    code = "tool_error"
    retryable = False


class ToolNotFoundError(ToolError):
    code = "unknown_tool"
    retryable = True


class ToolValidationError(ToolError):
    """Arguments did not match the tool's schema."""

    code = "invalid_arguments"
    retryable = True

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ToolExecutionError(ToolError):
    code = "execution_failed"


class ConfirmationRequiredError(ToolError):
    """The tool needs human confirmation that was not granted."""

    code = "confirmation_required"

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class SafetyBlockedError(ToolError):
    """The SafetyLayer refused the call outright (no confirmation can allow it)."""

    code = "blocked_by_safety"

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ToolBudgetExceededError(ToolError):
    """A hard limit of the tool itself was hit (size, results, timeout)."""

    code = "limit_exceeded"
