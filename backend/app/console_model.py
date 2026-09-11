"""The model the console drives: a real web LLM through the M1/M6 stack.

The console does not get a special model. It gets exactly what the CLI gets —
a BrowserModel over the Playwright provider — wrapped in the M6 BrowserRecovery
so a crashed page or an expired login is recovered instead of killing the run.

One thread owns the browser
---------------------------

Playwright's synchronous objects belong to the thread that created them, and the
console starts every run (and every question) on a NEW worker thread. Building
the session in whichever thread happened to run first therefore broke every
later run:

    cannot switch to a different thread (which happens to have exited)

Instead, one dedicated thread owns the session for the life of the process and
every browser call is marshalled to it. That also has a pleasant side effect:
the page stays open between runs, so the console keeps talking in the SAME
conversation instead of starting a new chat for every question.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from .agents.llm import BrowserModel, ModelClient
from .browser.artifacts import ArtifactStore
from .browser.driver import BrowserDriver
from .browser.profiles import load_profile
from .browser.web_chat import WebChatProvider
from .recovery import BrowserRecovery
from .settings import SettingsStore


class BrowserThread:
    """A thread that owns the browser session and runs every call on it."""

    def __init__(self, factory: Callable[[], Any], name: str = "console-browser") -> None:
        self._factory = factory
        self._requests: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self._session: Any = None
        self._closed = False
        self._thread.start()

    @property
    def ident(self) -> int | None:
        return self._thread.ident

    def _serve(self) -> None:  # pragma: no cover - exercised through call()
        while True:
            item = self._requests.get()
            if item is None:
                break
            function, box, done = item
            try:
                if self._session is None and not self._closed:
                    self._session = self._factory()
                box["result"] = function(self._session)
            except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
                box["error"] = exc
            finally:
                done.set()
        # the loop is over: release the browser on the thread that owns it
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def call(self, function: Callable[[Any], Any]) -> Any:
        """Run 'function(session)' on the owning thread and return its result."""
        if self._closed:
            raise RuntimeError("the browser thread is closed")
        box: dict[str, Any] = {}
        done = threading.Event()
        self._requests.put((function, box, done))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._requests.put(None)
        self._thread.join(timeout=30)


class ThreadBoundProvider:
    """The provider surface, every call marshalled onto the browser thread.

    A failed call is offered one recovery attempt (M6): the page is re-opened on
    the same thread and, when that succeeds, the call is retried once. Nothing
    retries forever, and a recovery that fails re-raises the original error.
    """

    def __init__(self, browser: BrowserThread, login_timeout_ms: int = 30_000) -> None:
        self._browser = browser
        self._login_timeout_ms = login_timeout_ms

    def _call(self, function: Callable[[Any], Any]) -> Any:
        try:
            return self._browser.call(function)
        except Exception:
            if not self._recover():
                raise
            return self._browser.call(function)

    def _recover(self) -> bool:
        try:
            return bool(
                self._browser.call(
                    lambda session: session.provider.recover_session(self._login_timeout_ms)
                )
            )
        except Exception:
            return False

    def ask(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        return self._call(lambda session: session.provider.ask(prompt, *args, **kwargs))

    def ask_stream(self, prompt: str, on_delta: Any, *args: Any, **kwargs: Any) -> Any:
        return self._call(
            lambda session: session.provider.ask_stream(prompt, on_delta, *args, **kwargs)
        )

    def is_logged_in(self) -> bool:
        return bool(self._browser.call(lambda session: session.provider.is_logged_in()))

    def open(self, new_conversation: bool = False) -> None:
        self._browser.call(lambda session: session.provider.open(new_conversation))


class ConsoleModel:
    """A lazily created, recoverable browser session shared by console runs."""

    def __init__(self, settings: SettingsStore | None = None) -> None:
        self.settings_store = settings or SettingsStore()
        # Reentrant: model()/recovery() hold it while asking for the browser
        # thread, and a plain Lock deadlocked the console there (found by a test
        # that hung instead of failing).
        self._lock = threading.RLock()
        self._browser: BrowserThread | None = None
        self._recovery: BrowserRecovery | None = None
        self._model: BrowserModel | None = None

    # -- the session -------------------------------------------------------

    def _factory(self) -> Any:
        settings = self.settings_store.load()
        profile = load_profile(settings.provider.name)
        driver = BrowserDriver(
            profile_dir=settings.browser.profile_dir or None,
            artifacts=ArtifactStore(
                base_dir=settings.browser.artifacts_dir or None, run_name=profile.name
            ),
        ).start()
        provider = WebChatProvider(driver, profile)
        session = type("Session", (), {})()
        session.driver = driver
        session.provider = provider
        session.close = driver.close
        return session

    def _thread_for_browser(self) -> BrowserThread:
        with self._lock:
            if self._browser is None:
                self._browser = BrowserThread(self._factory)
            return self._browser

    def recovery(self) -> BrowserRecovery:
        """M6 recovery for the console's ONE browser session.

        The factory marshals onto the browser thread, so a restart still happens
        on the thread that owns Playwright.
        """
        with self._lock:
            if self._recovery is None:
                browser = self._thread_for_browser()
                self._recovery = BrowserRecovery(lambda: browser.call(lambda session: session))
            return self._recovery

    def model(self) -> ModelClient:
        """The ModelClient handed to a run.

        Every call is marshalled onto the one browser thread, so a run started
        from any worker thread can use the session (see the module docstring).
        """
        with self._lock:
            if self._model is None:
                self._model = BrowserModel(
                    provider=ThreadBoundProvider(self._thread_for_browser())
                )
            return self._model

    def close(self) -> None:
        with self._lock:
            browser, self._browser = self._browser, None
            self._recovery = None
            self._model = None
        if browser is not None:
            browser.close()
