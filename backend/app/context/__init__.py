"""Context / State layer (M2).

Four kinds of data stay distinct, per docs/state-context.md:

* Context      - what this turn actually sends to the model (ContextBuilder)
* Transcript   - the immutable record of what was said (TranscriptStore)
* ProjectState - where the project currently stands (app.models.ProjectState)
* Memory       - long-lived knowledge, writable only through review (MemoryStore)

Sessions (SessionManager) tie them together and survive a restart.
"""

from .builder import (
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
    ContextBuilder,
    clip,
    render_project_state,
    render_untrusted,
)
from .memory import MemoryStore
from .models import (
    SECTION_ORDER,
    BuiltContext,
    ContextBudget,
    ContextSection,
    MemoryDecision,
    MemoryProposal,
    MemoryReviewResult,
    SessionIndex,
    SessionInfo,
    SessionRotation,
    SessionSnapshot,
    TranscriptEntry,
    TranscriptSummary,
    utc_now,
)
from .session import SessionManager
from .transcript import TranscriptError, TranscriptStore

__all__ = [
    "BuiltContext",
    "ContextBudget",
    "ContextBuilder",
    "ContextSection",
    "MemoryDecision",
    "MemoryProposal",
    "MemoryReviewResult",
    "MemoryStore",
    "SECTION_ORDER",
    "SessionIndex",
    "SessionInfo",
    "SessionManager",
    "SessionRotation",
    "SessionSnapshot",
    "TranscriptEntry",
    "TranscriptError",
    "TranscriptStore",
    "TranscriptSummary",
    "UNTRUSTED_CLOSE",
    "UNTRUSTED_OPEN",
    "clip",
    "render_project_state",
    "render_untrusted",
    "utc_now",
]
