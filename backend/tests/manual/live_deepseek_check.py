"""Live check against a REAL web LLM: two questions, ONE conversation.

Not collected by pytest (the filename is not test_*.py): it opens a headed
browser and talks to a real site.

    cd backend
    ../.venv/Scripts/python.exe tests/manual/live_deepseek_check.py

What it proves:

* the browser provider really drives chat.deepseek.com (profile deepseek-web)
* the page is driven the way a person drives it: the mouse moves to the
  composer, the text is typed character by character with a variable rhythm,
  and there is a pause before Enter
* the SECOND question continues the SAME conversation - the page is not
  reloaded and no new chat is started

The scratch artifacts go to runs/; the logged-in session comes from the repo's
persistent browser profile, so no credentials are touched. Login, captcha and
risk-control flows are never automated (project rule).

Exit code 0 means every assertion held.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.browser.artifacts import ArtifactStore
from app.browser.driver import BrowserDriver
from app.browser.profiles import load_profile
from app.browser.web_chat import WebChatProvider

REPO = pathlib.Path(__file__).resolve().parents[3]
PROFILE = "deepseek-web"
FIRST = "Reply with exactly: E2E-ONE"
SECOND = "Now reply with exactly: E2E-TWO"

profile = load_profile(PROFILE)
print("profile  :", profile.name, profile.url)
print("human    :", profile.human.enabled, profile.human.typing_min_ms, "-", profile.human.typing_max_ms, "ms/char")
print("reuse    :", profile.reuse_conversation)

driver = BrowserDriver(
    profile_dir=REPO / ".browser-profile",
    artifacts=ArtifactStore(base_dir=REPO / "runs", run_name="live-deepseek"),
).start()
try:
    provider = WebChatProvider(driver, profile)
    provider.open()
    print("opened   :", driver.page_url(), "| reused:", provider.reused_conversation)
    print("toggles  :", provider.toggles_on or "(none)")
    assert provider.toggles_on, "the thinking switch was not switched on"

    navigations_before = driver.page_url()
    first = provider.ask(FIRST, timeout_ms=180_000)
    print()
    print("[1] reply      :", repr(first.text[:200]))
    print("    completed  :", first.completed, "timed_out:", first.timed_out)
    print("    duration   :", first.duration_ms, "ms | capture:", first.source)
    print("    url now    :", driver.page_url())
    assert "E2E-ONE" in first.text, "the first answer did not come back: " + repr(first.text[:200])

    # The caller opens before every question (this is what the CLI and the
    # console do). The second open must find the page already on the site and
    # continue the conversation instead of navigating.
    conversation_url = provider._conversation_url
    provider.open()
    print()
    print("[2] before ask : url unchanged:", driver.page_url() == conversation_url,
          "| reused:", provider.reused_conversation)
    assert provider.reused_conversation is True, "the second question would start a new chat"
    assert driver.page_url() == conversation_url

    second = provider.ask(SECOND, timeout_ms=180_000)
    print()
    print("[2] reply      :", repr(second.text[:200]))
    print("    completed  :", second.completed, "timed_out:", second.timed_out)
    print("    duration   :", second.duration_ms, "ms | capture:", second.source)
    print("    url now    :", driver.page_url())
    print("    reused     :", provider.reused_conversation)
    assert "E2E-TWO" in second.text, "the second answer did not come back: " + repr(second.text[:200])

    # the same conversation: no navigation between the two questions, and the
    # conversation URL is the one the first exchange created
    assert driver.page_url() == conversation_url, "the conversation moved"
    print()
    print("human actions:", json.dumps(provider.human.summary(), ensure_ascii=False))
    rhythm = provider.human.summary().get("characters", {})
    assert rhythm.get("fast", 0) and rhythm.get("slow", 0), (
        "the typing rhythm must mix fast and slow characters: " + str(rhythm)
    )
    print()
    print("LIVE DEEPSEEK CHECK: PASS (two questions, one conversation)")
finally:
    driver.close()
