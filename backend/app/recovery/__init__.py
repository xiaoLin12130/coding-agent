"""Recovery layer (M6).

Continues a task after something broke:

| Module | Failure it handles |
| --- | --- |
| `thresholds.py` | context filling up (soft / hard ratios) |
| `session_recovery.py` | the documented Context-full sequence, with the injections verified |
| `run_recovery.py` | the program restarted (checkpoint -> continue) |
| `browser_recovery.py` | the browser crashed, or the login expired |
| `snapshot.py` | a WebSocket client reconnected and needs to re-sync |

The AgentLoop consults the thresholds at every step boundary, so a long task
rots into a fresh session instead of overflowing the context.
"""

from .browser_recovery import (
    MANUAL_LOGIN_TIMEOUT_MS,
    BrowserRecovery,
    BrowserSessionFactory,
    default_probe,
)
from .models import (
    ContextPressure,
    ContextThresholds,
    PressureLevel,
    RecoveryKind,
    RecoveryOutcome,
    RecoveryReport,
    RecoverySnapshot,
    RecoveryStep,
    RunRecoveryPlan,
)
from .run_recovery import RunRecovery
from .session_recovery import SessionRecovery
from .snapshot import build_snapshot
from .thresholds import ContextPressurePolicy

__all__ = [
    "BrowserRecovery",
    "BrowserSessionFactory",
    "ContextPressure",
    "ContextPressurePolicy",
    "ContextThresholds",
    "MANUAL_LOGIN_TIMEOUT_MS",
    "PressureLevel",
    "RecoveryKind",
    "RecoveryOutcome",
    "RecoveryReport",
    "RecoverySnapshot",
    "RecoveryStep",
    "RunRecovery",
    "RunRecoveryPlan",
    "SessionRecovery",
    "build_snapshot",
    "default_probe",
]
