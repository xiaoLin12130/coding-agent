"""MemoryStore tests: the memory_propose review pipeline."""

from __future__ import annotations

from pathlib import Path

from app.context.memory import MemoryStore
from app.context.models import MemoryProposal


def _store(tmp_path: Path) -> MemoryStore:
    from app.config import AppPaths
    from app.storage import StateStore

    paths = AppPaths(
        project_root=tmp_path,
        state_dir=tmp_path,
        project_state_file=tmp_path / "project_state.json",
        memory_file=tmp_path / "memory.json",
    )
    return MemoryStore(StateStore(paths))


def test_accepted_proposal_is_written(tmp_path: Path) -> None:
    store = _store(tmp_path)
    decision = store.propose(
        MemoryProposal(key="stack", value="fastapi + react", reason="decided in M0")
    )

    assert decision.decision == "accepted"
    assert decision.stored_key == "user/stack"
    entries = store.all()
    assert len(entries) == 1
    assert entries[0].key == "stack"
    assert entries[0].value == "fastapi + react"
    assert entries[0].updated_by == "model"
    assert entries[0].created_at


def test_empty_key_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(MemoryProposal(key="  ", value="v"))
    assert decision.decision == "rejected_invalid"
    assert "key" in decision.reason


def test_empty_value_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(MemoryProposal(key="k", value="   "))
    assert decision.decision == "rejected_invalid"
    assert "value" in decision.reason


def test_oversized_value_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(
        MemoryProposal(key="k", value="x" * 5000)
    )
    assert decision.decision == "rejected_invalid"
    assert "longer than" in decision.reason


def test_identical_value_is_a_duplicate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="a", value="same fact"))

    decision = store.propose(MemoryProposal(key="b", value="Same   Fact."))

    assert decision.decision == "duplicate"
    assert decision.stored_key == "user/a"
    assert len(store.all()) == 1, "a duplicate must not be written"


def test_same_key_different_value_is_a_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="port", value="8000"))

    decision = store.propose(MemoryProposal(key="port", value="9000"))

    assert decision.decision == "conflict"
    assert "explicit update" in decision.reason
    assert store.get("port").value == "8000", "conflict must not overwrite"


def test_conflict_can_be_resolved_by_explicit_update(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="port", value="8000"))

    updated = store.update("port", "9000", updated_by="user")

    assert updated.value == "9000"
    assert updated.updated_by == "user"
    assert len(store.all()) == 1


def test_update_of_unknown_key_raises(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(KeyError):
        _store(tmp_path).update("ghost", "v")


def test_different_namespace_does_not_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="note", value="one", namespace="project"))

    decision = store.propose(
        MemoryProposal(key="note", value="two", namespace="user")
    )

    assert decision.decision == "accepted"
    assert len(store.all()) == 2


# --- sensitive check: never persist a credential -------------------------


def test_api_key_assignment_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(
        MemoryProposal(key="cc", value="api_key = sk-abcdefghijklmnopqrstuvwx")
    )
    assert decision.decision == "rejected_sensitive"


def test_private_key_block_is_rejected(tmp_path: Path) -> None:
    value = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
    decision = _store(tmp_path).propose(MemoryProposal(key="k", value=value))
    assert decision.decision == "rejected_sensitive"
    assert "private key" in decision.reason


def test_github_token_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(
        MemoryProposal(key="gh", value="ghp_" + "a" * 30)
    )
    assert decision.decision == "rejected_sensitive"


def test_aws_key_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(
        MemoryProposal(key="aws", value="AKIAIOSFODNN7EXAMPLE")
    )
    assert decision.decision == "rejected_sensitive"


def test_bearer_token_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(
        MemoryProposal(key="hdr", value="Authorization: Bearer " + "a" * 30)
    )
    assert decision.decision == "rejected_sensitive"


def test_password_assignment_is_rejected(tmp_path: Path) -> None:
    decision = _store(tmp_path).propose(
        MemoryProposal(key="db", value="password: hunter2hunter2")
    )
    assert decision.decision == "rejected_sensitive"


def test_sensitive_check_can_be_called_directly() -> None:
    assert MemoryStore.sensitive_reason("k", "just a normal note") is None
    assert MemoryStore.sensitive_reason("k", "token = abc123") is not None


# --- batch behaviour ------------------------------------------------------


def test_batch_reviews_every_proposal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.propose_many(
        [
            MemoryProposal(key="good", value="keep me"),
            MemoryProposal(key="blank", value=""),
            MemoryProposal(key="leak", value="password: supersecret"),
        ]
    )

    assert len(result.decisions) == 3
    assert result.counts() == {
        "accepted": 1,
        "rejected_invalid": 1,
        "rejected_sensitive": 1,
    }
    assert [d.proposal.key for d in result.accepted] == ["good"]
    assert len(result.rejected) == 2
    assert [e.key for e in store.all()] == ["good"]


def test_batch_deduplicates_against_earlier_batch_items(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.propose_many(
        [
            MemoryProposal(key="one", value="the same fact"),
            MemoryProposal(key="two", value="the same fact"),
        ]
    )

    assert result.counts() == {"accepted": 1, "duplicate": 1}
    assert len(store.all()) == 1


def test_cache_is_untouched_when_nothing_is_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = (tmp_path / "memory.json").read_text(encoding="utf-8") if (tmp_path / "memory.json").exists() else None

    store.propose(MemoryProposal(key="x", value="password: nope"))

    after = (tmp_path / "memory.json").read_text(encoding="utf-8") if (tmp_path / "memory.json").exists() else None
    assert after == before, "a fully rejected batch must not rewrite memory.json"


# --- reading / maintenance ------------------------------------------------


def test_search_matches_key_value_and_namespace(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="port", value="8000", namespace="project"))
    store.propose(MemoryProposal(key="style", value="dark theme"))

    assert [e.key for e in store.search("port")] == ["port"]
    assert [e.key for e in store.search("8000")] == ["port"]
    assert [e.key for e in store.search("project")] == ["port"]
    assert len(store.search("  ")) == 2, "a blank query returns everything"
    assert store.search("nothing here") == []


def test_delete_removes_an_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="gone", value="bye"))

    assert store.delete("gone") is True
    assert store.delete("gone") is False
    assert store.count() == 0


def test_get_is_namespace_aware(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.propose(MemoryProposal(key="k", value="user value", namespace="user"))
    store.propose(MemoryProposal(key="k", value="proj value", namespace="project"))

    assert store.get("k", "user").value == "user value"
    assert store.get("k", "project").value == "proj value"
    assert store.get("k", "absent") is None
