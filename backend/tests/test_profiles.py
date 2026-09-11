"""Provider profile loading tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.browser.errors import ProfileError
from app.browser.models import ProviderProfile
from app.browser.profiles import list_profiles, load_profile, save_profile
from tests.conftest import PROFILES_DIR


def test_mock_profile_loads_with_expected_fields() -> None:
    profile = load_profile("mock", PROFILES_DIR)

    assert profile.name == "mock"
    assert profile.url.startswith("http://127.0.0.1")
    assert profile.input_selector
    assert profile.assistant_message_selector
    assert profile.verified is True
    assert profile.completion.timeout_ms > 0


def test_profile_can_be_loaded_by_path(tmp_path: Path) -> None:
    source = PROFILES_DIR / "mock.json"
    copy = tmp_path / "copy.json"
    copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    profile = load_profile(str(copy))
    assert profile.name == "mock"


def test_example_profile_is_present_and_marked_unverified() -> None:
    profile = load_profile("example-web-llm", PROFILES_DIR)

    assert profile.verified is False
    assert "Unverified" in profile.notes


def test_missing_profile_raises(tmp_path: Path) -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile("nope", tmp_path)
    assert excinfo.value.code == "profile_error"


def test_invalid_json_raises(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile("broken", tmp_path)


def test_non_object_profile_raises(tmp_path: Path) -> None:
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile("list", tmp_path)


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    payload = json.loads((PROFILES_DIR / "mock.json").read_text(encoding="utf-8"))
    payload["surprise"] = True
    (tmp_path / "extra.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProfileError):
        load_profile("extra", tmp_path)


def test_url_without_scheme_is_rejected(tmp_path: Path) -> None:
    payload = json.loads((PROFILES_DIR / "mock.json").read_text(encoding="utf-8"))
    payload["url"] = "127.0.0.1:8000"
    (tmp_path / "noscheme.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProfileError):
        load_profile("noscheme", tmp_path)


def test_missing_required_selector_is_rejected(tmp_path: Path) -> None:
    payload = json.loads((PROFILES_DIR / "mock.json").read_text(encoding="utf-8"))
    del payload["input_selector"]
    (tmp_path / "noselector.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProfileError):
        load_profile("noselector", tmp_path)


def test_save_and_reload_round_trip(tmp_path: Path) -> None:
    profile = load_profile("mock", PROFILES_DIR).model_copy(
        update={"name": "round-trip", "verified": False}
    )
    path = save_profile(profile, tmp_path)

    assert path.exists()
    assert load_profile("round-trip", tmp_path) == profile


def test_list_profiles_includes_shipped_profiles() -> None:
    names = list_profiles(PROFILES_DIR)

    assert "mock" in names
    assert "example-web-llm" in names
    assert list_profiles(Path(PROFILES_DIR) / "missing") == []


def test_profile_model_defaults() -> None:
    profile = ProviderProfile(name="x", url="http://127.0.0.1/", input_selector="textarea", assistant_message_selector=".m")

    assert profile.completion.timeout_ms == 120_000
    assert profile.network_response_patterns == []
    assert profile.verified is False
