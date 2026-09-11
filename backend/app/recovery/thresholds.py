"""Context pressure policy: soft and hard thresholds.

docs/M6 requires both:

* soft  - the context is filling up; carry less, keep the session
* hard  - the context is full; run the documented rotation sequence

Ratios rather than absolute sizes, so the policy follows whatever budget the
M2 builder is configured with.
"""

from __future__ import annotations

from ..context.builder import BuiltContext
from .models import ContextPressure, ContextThresholds


class ContextPressurePolicy:
    def __init__(self, thresholds: ContextThresholds | None = None) -> None:
        self.thresholds = thresholds or ContextThresholds()
        self.thresholds.validate_order()

    def evaluate(self, context: BuiltContext | None, budget_chars: int | None = None) -> ContextPressure:
        """Classify one assembled context."""
        if context is None:
            return ContextPressure(
                level="ok", used_chars=0, budget_chars=budget_chars or 0, ratio=0.0
            )

        budget = budget_chars or context.budget_chars or 0
        used = context.total_chars
        ratio = (used / budget) if budget > 0 else 1.0

        if ratio >= self.thresholds.hard_ratio:
            level = "hard"
        elif ratio >= self.thresholds.soft_ratio:
            level = "soft"
        else:
            level = "ok"

        return ContextPressure(
            level=level,  # type: ignore[arg-type]
            used_chars=used,
            budget_chars=budget,
            ratio=round(ratio, 4),
            dropped_sections=list(context.dropped_sections),
        )

    def recent_turns_for(self, level: str, default: int) -> int:
        """How many recent turns to carry at this pressure level."""
        if level == "hard":
            return self.thresholds.min_recent_turns
        if level == "soft":
            return max(self.thresholds.min_recent_turns, min(self.thresholds.soft_recent_turns, default))
        return default

    def would_overflow(self, used_chars: int, budget_chars: int) -> bool:
        if budget_chars <= 0:
            return True
        return (used_chars / budget_chars) >= self.thresholds.hard_ratio
