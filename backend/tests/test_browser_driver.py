"""BrowserDriver tests: headed launch, persistent profile, screenshots, DOM."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.artifacts import ArtifactStore
from app.browser.driver import BrowserDriver
from app.browser.errors import BrowserConfigError
from tests.conftest import make_driver

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_headless_mode_is_refused() -> None:
    with pytest.raises(BrowserConfigError) as excinfo:
        BrowserDriver(headless=True)
    assert excinfo.value.code == "browser_config_error"


def test_start_creates_persistent_profile_directory(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    driver = make_driver(tmp_path, profile_dir=profile_dir)
    try:
        assert profile_dir.exists()
        assert any(profile_dir.iterdir()), "chromium should write profile data"
    finally:
        driver.close()


def test_navigate_and_dom_snapshot(driver: BrowserDriver, fixture_site) -> None:
    driver.navigate(fixture_site.base_url)
    snapshot = driver.dom_snapshot(label="dom")

    assert snapshot.url == fixture_site.base_url
    assert snapshot.html_path is not None
    assert snapshot.text_path is not None
    html = Path(snapshot.html_path).read_text(encoding="utf-8")
    assert 'id="composer"' in html
    assert snapshot.html_bytes > 0
    assert snapshot.text_chars > 0
    assert Path(snapshot.html_path).parent == driver.artifacts.run_dir


def test_screenshot_is_written_as_png(driver: BrowserDriver, fixture_site) -> None:
    driver.navigate(fixture_site.base_url)
    path = driver.screenshot(label="shot")

    assert path.exists()
    assert path.read_bytes()[:8] == PNG_MAGIC
    assert str(path) in driver.artifacts.screenshots


def test_network_capture_records_document_response(
    driver: BrowserDriver, fixture_site
) -> None:
    driver.navigate(fixture_site.base_url)
    entries = driver.network(url_patterns=[fixture_site.base_url])

    assert entries, "the document response should be captured"
    assert entries[0].status == 200
    assert "text/html" in entries[0].content_type


def test_missing_elements_are_reported_safely(driver: BrowserDriver, fixture_site) -> None:
    driver.navigate(fixture_site.base_url)

    assert driver.last_text("#does-not-exist") == ""
    assert driver.is_visible("#does-not-exist") is False
    assert driver.click_last("#does-not-exist") is False
    assert driver.wait_for_selector("#does-not-exist", timeout_ms=300) is False
    assert driver.is_visible(None) is False


def test_profile_persists_between_sessions(tmp_path: Path, fixture_site, second_driver) -> None:
    profile_dir = tmp_path / "persistent-profile"

    first = second_driver(profile_dir=profile_dir)
    first.navigate(fixture_site.base_url)
    first.page.evaluate("() => window.localStorage.setItem('m1-test', 'kept')")
    first.close()

    second = second_driver(profile_dir=profile_dir)
    second.navigate(fixture_site.base_url)
    stored = second.page.evaluate("() => window.localStorage.getItem('m1-test')")

    assert stored == "kept", "the persistent profile must keep session state"


def test_artifact_store_isolates_runs(tmp_path: Path) -> None:
    store = ArtifactStore(base_dir=tmp_path / "runs", run_name="unit")
    store.write_json("log.json", {"ok": True})
    store.write_text("note.txt", "hello")

    assert store.run_dir.exists()
    assert (store.run_dir / "log.json").exists()
    assert (store.run_dir / "note.txt").read_text(encoding="utf-8") == "hello"
    assert store.next_path("shot", ".png").name == "shot-1.png"
    assert store.next_path("shot", ".png").name == "shot-2.png"
