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
    """A tool ran but failed.

    'retryable' is opt-in: a missing file will still be missing on the next
    attempt, while a timeout or a transient I/O error may not be. Tools mark
    the transient cases explicitly so the agent loop knows what is worth
    retrying.
    """

    code = "execution_failed"

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.details = details or {}
        self.retryable = retryable


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
