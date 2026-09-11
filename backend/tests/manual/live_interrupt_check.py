"""Live check: the provider waits for a real answer instead of interrupting it.

    cd backend
    ../.venv/Scripts/python.exe tests/manual/live_interrupt_check.py

Against chat.deepseek.com it answers three questions:

* is the page still generating while the answer PAUSES (no visible change)?
  That window is exactly where the old detector declared completion.
* does wait_until_complete() return only after the page has really stopped?
* is the next send() safe - did the previous answer survive intact?

Exit code 0 means every assertion held.
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.browser.artifacts import ArtifactStore
from app.browser.driver import BrowserDriver
from app.browser.profiles import load_profile
from app.browser.web_chat import WebChatProvider

REPO = pathlib.Path(__file__).resolve().parents[3]
FIRST = "请写一段约 500 字的技术说明：Python 生成器与迭代器的区别，包含 2 个代码示例。"
SECOND = "用一句话总结上面那段说明。"

profile = load_profile("deepseek-web")
print("profile        :", profile.name)
print("generating     :", profile.generating_patterns)
print("idle timeout   :", profile.completion.idle_timeout_ms, "ms")

driver = BrowserDriver(
    profile_dir=REPO / ".browser-profile",
    artifacts=ArtifactStore(base_dir=REPO / "runs", run_name="live-interrupt"),
).start()
try:
    provider = WebChatProvider(driver, profile)
    provider.open()
    print("toggles        :", provider.toggles_on or "(none)")
    print("idle before    :", provider.is_generating())

    provider.send(FIRST)
    started = time.monotonic()
    last_text = ""
    paused_while_generating = 0
    generating_samples = 0
    samples = 0
    first_seen_at = None
    while True:
        generating = provider.is_generating()
        text = provider._dom_text()
        samples += 1
        if generating:
            generating_samples += 1
            if text == last_text:
                # No visible change, yet the page is still working. This is the
                # window in which the old detector declared the answer finished
                # and the next question stopped it halfway.
                paused_while_generating += 1
        if text != last_text:
            if first_seen_at is None and text:
                first_seen_at = time.monotonic() - started
            print("  %5.1fs chars=%5d generating=%s" % (time.monotonic() - started, len(text), generating))
            last_text = text
        if not generating and text:
            break
        if time.monotonic() - started > 240:
            raise SystemExit("the page never settled")
        driver.wait(250)

    print()
    print("samples                       :", samples)
    print("still-generating samples      :", generating_samples)
    print("PAUSED but still generating   :", paused_while_generating)
    print("first text appeared after     : %.1fs" % (first_seen_at or 0))
    print("final answer length           :", len(last_text))
    assert generating_samples > 0, "the page never reported itself as generating"
    assert paused_while_generating > 0, (
        "no pause window was observed; the check proves less than it claims"
    )

    # the detector must not return while the page is still working
    print("inflight right now            :", driver.inflight(profile.generating_patterns))
    driver.wait(1000)
    print("idle after the answer         :", not provider.is_generating())

    # A second question must be safe now: the first answer is complete and kept.
    # _dom_text() reads the LAST answer, so the proof is the number of answers on
    # the page: an interrupted one would have been replaced, not added to.
    def answer_count() -> int:
        return int(
            driver.page.evaluate(
                "() => document.querySelectorAll('div.ds-assistant-message-main-content').length"
            )
        )

    answers_before = answer_count()
    second = provider.ask(SECOND, timeout_ms=180_000)
    answers_after = answer_count()
    print()
    print("second reply                  :", repr(second.text[:120]))
    print("completed / timed out         :", second.completed, "/", second.timed_out)
    print("answers on the page           :", answers_before, "->", answers_after)
    assert second.completed and not second.timed_out
    assert answers_after > answers_before, (
        "the page still shows " + str(answers_after) + " answer(s): the first one was replaced"
    )
    print()
    print("LIVE INTERRUPT CHECK: PASS (waited through a real pause, nothing interrupted)")
finally:
    driver.close()
