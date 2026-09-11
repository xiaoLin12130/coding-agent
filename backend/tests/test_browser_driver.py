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

# --- reading an answer that contains page chrome (M12) ---------------------


CHROME_PAGE = """
<!doctype html>
<html><body>
<div id="answer">
  <div class="md-code-block">
    <div class="md-code-block-banner-wrap">
      <span class="lang">python</span>
      <div role="button" class="copy">复制</div>
      <div role="button" class="download">下载</div>
    </div>
    <pre><code>def add(a, b):
    return a + b</code></pre>
  </div>
</div>
</body></html>
"""


def test_reading_an_answer_can_leave_out_the_page_chrome(driver) -> None:
    """The code-block banner must not become part of the model's reply."""
    driver.page.set_content(CHROME_PAGE)

    raw = driver.last_text("#answer")
    assert "复制" in raw and "python" in raw, "the chrome is really inside the element"

    clean = driver.last_text(
        "#answer", ignore_selectors=["div.md-code-block-banner-wrap", "div[role='button']"]
    )
    assert "复制" not in clean and "下载" not in clean
    assert "python" not in clean, "the language label is chrome too"
    assert "def add(a, b):" in clean
    assert "    return a + b" in clean, "the indentation survives"
    # and the page is left as it was
    assert "复制" in driver.last_text("#answer")


def test_reading_an_answer_without_ignore_selectors_is_unchanged(driver) -> None:
    driver.page.set_content(CHROME_PAGE)
    assert driver.last_text("#answer") == driver.last_text("#answer", ignore_selectors=[])

# --- code blocks are read exactly (M12) ------------------------------------


CODE_PAGE = """
<!doctype html>
<html><head><style>
  /* the site's own styling is what folds the rendered indentation */
  .md-code-block pre { white-space: pre-wrap; }
</style></head><body>
<div id="answer">
  <p>Here is the file:</p>
  <div class="md-code-block">
    <div class="md-code-block-banner-wrap"><span>python</span>
      <div role="button">复制</div></div>
    <pre><code>def add(a, b):
    return a + b


def sub(a, b):
    return a - b</code></pre>
  </div>
  <p>That is all.</p>
</div>
</body></html>
"""


def test_a_code_block_is_read_with_its_real_text(driver) -> None:
    driver.page.set_content(CODE_PAGE)

    text = driver.answer_text(
        "#answer",
        ignore_selectors=["div.md-code-block-banner-wrap", "div[role='button']"],
        code_block_selector="div.md-code-block",
    )

    assert "def add(a, b):" in text
    assert "    return a + b" in text, "the indentation of the code survived"
    assert "    return a - b" in text
    assert "复制" not in text
    assert "Here is the file:" in text, "the prose around it is still there"
    assert "That is all." in text


def test_without_a_code_block_selector_the_reader_stays_on_inner_text(driver) -> None:
    driver.page.set_content(CODE_PAGE)
    text = driver.answer_text("#answer")
    assert "def add(a, b):" in text
