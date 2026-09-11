"""MemoryStore: long-lived knowledge with a review gate.

The model may only PROPOSE memory (docs/state-context.md). This module owns
the system side of that boundary:

    filter -> deduplicate -> conflict detection -> sensitive check -> write

Nothing else in the codebase writes state/memory.json; StateStore remains the
single writer of that file.
"""

from __future__ import annotations

import re
import unicodedata

from ..models import Memory, MemoryEntry
from ..storage import StateStore
from .models import (
    MemoryDecision,
    MemoryProposal,
    MemoryReviewResult,
    utc_now,
)

# Patterns that must never be persisted as memory. Matching is deliberately
# broad: a false positive costs one rejected proposal, a false negative leaks
# a credential into a file that is committed and shown in the UI.
SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"\bssh-rsa\s+[A-Za-z0-9+/=]{32,}", "ssh public key"),
    (r"\bsk-[A-Za-z0-9_-]{16,}", "openai-style api key"),
    (r"\bsk-ant-[A-Za-z0-9_-]{16,}", "anthropic api key"),
    (r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", "aws access key id"),
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "github token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "slack token"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "jwt"),
    (r"(?i)\b(api[_-]?key|secret|password|passwd|token|credential)s?\b\s*[:=]\s*\S+", "credential assignment"),
    (r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}", "bearer token"),
)

MAX_KEY_CHARS = 120
MAX_VALUE_CHARS = 4_000


def normalize(text: str) -> str:
    """Normalisation used for duplicate detection only."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    collapsed = re.sub(r"\s+", " ", folded).strip()
    return collapsed.strip(" .;:,\t\n")


class MemoryStore:
    def __init__(self, store: StateStore | None = None) -> None:
        self.store = store or StateStore()

    # -- reading -----------------------------------------------------------

    def all(self) -> list[MemoryEntry]:
        return list(self.store.load_memory().memories)

    def get(self, key: str, namespace: str = "user") -> MemoryEntry | None:
        for entry in self.all():
            if entry.key == key and entry.namespace == namespace:
                return entry
        return None

    def search(self, query: str) -> list[MemoryEntry]:
        needle = normalize(query)
        if not needle:
            return self.all()
        return [
            entry
            for entry in self.all()
            if needle in normalize(entry.key)
            or needle in normalize(entry.value)
            or needle in normalize(entry.namespace)
        ]

    def count(self) -> int:
        return len(self.all())

    # -- direct maintenance (UI / administrative paths, not model-facing) ---

    def delete(self, key: str, namespace: str = "user") -> bool:
        memory = self.store.load_memory()
        remaining = [
            entry
            for entry in memory.memories
            if not (entry.key == key and entry.namespace == namespace)
        ]
        if len(remaining) == len(memory.memories):
            return False
        self.store.save_memory(Memory(memories=remaining))
        return True

    def update(
        self,
        key: str,
        value: str,
        namespace: str = "user",
        updated_by: str = "user",
        source: str | None = None,
    ) -> MemoryEntry:
        """Explicit overwrite of an existing entry (the conflict escape hatch)."""
        memory = self.store.load_memory()
        for entry in memory.memories:
            if entry.key == key and entry.namespace == namespace:
                entry.value = value
                entry.updated_by = updated_by
                entry.updated_at = utc_now().isoformat()
                if source is not None:
                    entry.source = source
                self.store.save_memory(memory)
                return entry
        raise KeyError(f"no memory entry {namespace}/{key}")

    # -- the review pipeline ----------------------------------------------

    def propose(self, proposal: MemoryProposal) -> MemoryDecision:
        """Run one proposal through the full pipeline."""
        return self.propose_many([proposal]).decisions[0]

    def propose_many(self, proposals: list[MemoryProposal]) -> MemoryReviewResult:
        """Review proposals in order; accepted ones are written immediately.

        Deduplication sees both the stored entries and the proposals accepted
        earlier in the same batch.
        """
        memory = self.store.load_memory()
        existing = list(memory.memories)
        decisions: list[MemoryDecision] = []

        for proposal in proposals:
            # 1. filter
            invalid = self._invalid_reason(proposal)
            if invalid is not None:
                decisions.append(
                    MemoryDecision(
                        proposal=proposal,
                        decision="rejected_invalid",
                        reason=invalid,
                    )
                )
                continue

            # 2. deduplicate
            duplicate = self._find_duplicate(existing, proposal)
            if duplicate is not None:
                decisions.append(
                    MemoryDecision(
                        proposal=proposal,
                        decision="duplicate",
                        reason=(
                            f"already stored as {duplicate.namespace}/{duplicate.key}"
                        ),
                        stored_key=f"{duplicate.namespace}/{duplicate.key}",
                    )
                )
                continue

            # 3. conflict detection
            conflicting = self._find_conflict(existing, proposal)
            if conflicting is not None:
                decisions.append(
                    MemoryDecision(
                        proposal=proposal,
                        decision="conflict",
                        reason=(
                            f"{conflicting.namespace}/{conflicting.key} already holds a "
                            "different value; use an explicit update to replace it"
                        ),
                        stored_key=f"{conflicting.namespace}/{conflicting.key}",
                    )
                )
                continue

            # 4. sensitive check
            hit = self.sensitive_reason(proposal.key, proposal.value)
            if hit is not None:
                decisions.append(
                    MemoryDecision(
                        proposal=proposal,
                        decision="rejected_sensitive",
                        reason=f"looks like a {hit}",
                    )
                )
                continue

            # 5. write
            now = utc_now().isoformat()
            entry = MemoryEntry(
                key=proposal.key.strip(),
                value=proposal.value.strip(),
                namespace=proposal.namespace,
                source=proposal.reason or "memory_propose",
                source_turn=proposal.source_turn,
                updated_by=proposal.proposed_by,
                created_at=now,
                updated_at=now,
            )
            existing.append(entry)
            decisions.append(
                MemoryDecision(
                    proposal=proposal,
                    decision="accepted",
                    reason="stored",
                    stored_key=f"{entry.namespace}/{entry.key}",
                )
            )

        accepted = [d for d in decisions if d.decision in ("accepted", "updated")]
        if accepted:
            self.store.save_memory(Memory(memories=existing))
        return MemoryReviewResult(decisions=decisions)

    # -- pipeline stages ---------------------------------------------------

    @staticmethod
    def _invalid_reason(proposal: MemoryProposal) -> str | None:
        key = proposal.key.strip()
        value = proposal.value.strip()
        if not key:
            return "key must not be empty"
        if not value:
            return "value must not be empty"
        if len(key) > MAX_KEY_CHARS:
            return f"key longer than {MAX_KEY_CHARS} characters"
        if len(value) > MAX_VALUE_CHARS:
            return f"value longer than {MAX_VALUE_CHARS} characters"
        return None

    @staticmethod
    def _find_duplicate(
        existing: list[MemoryEntry], proposal: MemoryProposal
    ) -> MemoryEntry | None:
        wanted = normalize(proposal.value)
        for entry in existing:
            if entry.namespace != proposal.namespace:
                continue
            if normalize(entry.value) == wanted:
                return entry
        return None

    @staticmethod
    def _find_conflict(
        existing: list[MemoryEntry], proposal: MemoryProposal
    ) -> MemoryEntry | None:
        for entry in existing:
            if entry.namespace == proposal.namespace and entry.key == proposal.key.strip():
                return entry
        return None

    @staticmethod
    def sensitive_reason(key: str, value: str) -> str | None:
        haystack = f"{key}\n{value}"
        for pattern, label in SENSITIVE_PATTERNS:
            if re.search(pattern, haystack):
                return label
        return None
