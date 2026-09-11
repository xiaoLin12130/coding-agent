"""Shared pytest fixtures.

State files and browser profiles are redirected to per-test tmp_path values so
tests never touch the real state/ or .browser-profile/ directories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.browser.artifacts import ArtifactStore
from app.browser.driver import BrowserDriver
from app.browser.errors import BrowserError
from app.browser.models import ProviderProfile
from app.browser.profiles import load_profile
from app.config import ENV_STATE_DIR
from app.main import app

# backend/ directory: profiles live in backend/profiles
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROFILES_DIR = BACKEND_DIR / "profiles"


@pytest.fixture()
def state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(ENV_STATE_DIR, str(tmp_path))
    (tmp_path / "project_state.json").write_text(
        json.dumps(
            {
                "current_milestone": "M0",
                "current_task": "T1",
                "todos": [{"content": "skeleton", "status": "in_progress"}],
                "files_changed": ["backend/app/main.py"],
                "tests": [],
                "failures": [],
                "decisions": [],
                "checkpoint": None,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "memory.json").write_text(
        json.dumps({"memories": [{"key": "stack", "value": "fastapi+react"}]}),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def client(state_files: Path) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Browser layer fixtures (M1)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fixture_site():
    """Deterministic local chat page (no real LLM involved)."""
    from fixtures.chat_site.server import FixtureSite

    site = FixtureSite().start()
    try:
        yield site
    finally:
        site.stop()


@pytest.fixture()
def mock_profile(fixture_site) -> ProviderProfile:
    """The shipped mock profile, pointed at the ephemeral fixture port."""
    profile = load_profile("mock", PROFILES_DIR)
    return profile.model_copy(update={"url": fixture_site.base_url})


def make_driver(tmp_path: Path, **kwargs) -> BrowserDriver:
    """Create and start a headed driver; skips when no browser can launch."""
    pytest.importorskip("playwright.sync_api")
    artifacts = kwargs.pop(
        "artifacts", ArtifactStore(base_dir=tmp_path / "runs", run_name="test")
    )
    driver = BrowserDriver(
        profile_dir=kwargs.pop("profile_dir", tmp_path / "browser-profile"),
        artifacts=artifacts,
        **kwargs,
    )
    try:
        return driver.start()
    except BrowserError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"headed browser unavailable: {exc}")


@pytest.fixture()
def driver(tmp_path: Path) -> BrowserDriver:
    instance = make_driver(tmp_path)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture()
def second_driver(tmp_path: Path):
    """Factory for extra drivers (persistence tests) closed at teardown."""
    created: list[BrowserDriver] = []

    def factory(**kwargs) -> BrowserDriver:
        instance = make_driver(tmp_path, **kwargs)
        created.append(instance)
        return instance

    yield factory
    for instance in created:
        instance.close()
