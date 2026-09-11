"""Safety layer (M4).

    ToolCall -> Validation -> SafetyLayer -> Confirmation -> Executor -> Tool

* policy.py    every rule in one place (roots, sensitive files, shell grading,
               injection patterns)
* paths.py     filesystem policy: nothing outside the project, no secrets
* shell.py     shell risk grading (LOW / MEDIUM / HIGH, deny-by-default)
* injection.py untrusted content is DATA; only model/user output may issue calls
* layer.py     SafetyLayer: allow / confirm / deny, session grants, output flags

The Executor always consults a SafetyLayer; there is no path that runs a tool
without one.
"""

from .injection import (
    ALLOWED_INSTRUCTION_SOURCES,
    InjectedInstructionError,
    assert_instruction_source,
    categories,
    scan_untrusted,
    wrap_untrusted,
)
from .layer import PATH_ARGUMENTS, SafetyLayer
from .models import (
    ConfirmationChoice,
    ConfirmationRequest,
    InjectionFinding,
    PathDecision,
    RiskLevel,
    SafetyDecision,
    SafetyError,
    SafetyVerdict,
    ShellAssessment,
)
from .paths import FilesystemPolicy, build_filesystem_policy, is_within
from .policy import SafetyPolicy
from .shell import ShellGrader

__all__ = [
    "ALLOWED_INSTRUCTION_SOURCES",
    "ConfirmationChoice",
    "ConfirmationRequest",
    "FilesystemPolicy",
    "InjectedInstructionError",
    "InjectionFinding",
    "PATH_ARGUMENTS",
    "PathDecision",
    "RiskLevel",
    "SafetyDecision",
    "SafetyError",
    "SafetyLayer",
    "SafetyPolicy",
    "SafetyVerdict",
    "ShellAssessment",
    "ShellGrader",
    "assert_instruction_source",
    "build_filesystem_policy",
    "categories",
    "is_within",
    "scan_untrusted",
    "wrap_untrusted",
]
