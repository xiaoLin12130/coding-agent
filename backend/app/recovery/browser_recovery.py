"""Browser recovery: keep a live, logged-in page.

Two failures M6 must survive:

* the browser crashed (the driver or context died)  -> restart it and reopen
* the login expired                                   -> wait for a manual sign-in

Recovery is deliberately bounded: a restart budget, a login timeout, and an
explicit report of what happened. Nothing here automates credentials; the
human signs in, exactly as M1 requires.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from .models import RecoveryReport, RecoveryStep

MANUAL_LOGIN_TIMEOUT_MS = 300_000


class BrowserSessionLike(Protocol):
    """What recovery needs from a browser session (driver + provider)."""

    driver: Any
    provider: Any

    def close(self) -> None:
        ...


BrowserSessionFactory = Callable[[], BrowserSessionLike]


def default_probe(session: BrowserSessionLike) -> bool:
    """True while the page still answers.

    Playwright raises once the page or context is closed, so simply asking the
    page a cheap question is the most reliable liveness check available.
    """
    try:
        session.driver.page_url()
        return True
    except Exception:
        return False


class BrowserRecovery:
    def __init__(
        self,
        factory: BrowserSessionFactory,
        probe: Callable[[BrowserSessionLike], bool] | None = None,
        max_restarts: int = 2,
        login_timeout_ms: int = MANUAL_LOGIN_TIMEOUT_MS,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.factory = factory
        self.probe = probe or default_probe
        self.max_restarts = max_restarts
        self.login_timeout_ms = login_timeout_ms
        self.on_event = on_event
        self._session: BrowserSessionLike | None = None
        self.restarts = 0

    # -- access ------------------------------------------------------------

    @property
    def session(self) -> BrowserSessionLike:
        if self._session is None:
            self._session = self.factory()
        return self._session

    def is_alive(self) -> bool:
        if self._session is None:
            return False
        return bool(self.probe(self._session))

    def _note(self, message: str) -> None:
        if self.on_event is not None:
            try:
                self.on_event(message)
            except Exception:  # pragma: no cover - an observer must not break recovery
                pass

    # -- recovery ----------------------------------------------------------

    def restart(self) -> RecoveryReport:
        """Discard the dead session and build a fresh one."""
        steps = [RecoveryStep(action="detected a dead browser session")]
        self._close_quietly()
        self._session = None

        if self.restarts >= self.max_restarts:
            return RecoveryReport(
                kind="browser_crash",
                outcome="failed",
                steps=steps,
                message="restart budget exhausted (" + str(self.max_restarts) + ")",
            )

        try:
            session = self.factory()
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return RecoveryReport(
                kind="browser_crash",
                outcome="failed",
                steps=steps + [RecoveryStep(action="relaunched the browser", ok=False, detail=str(exc))],
                message="could not relaunch the browser",
            )

        self.restarts += 1
        self._session = session
        steps.append(RecoveryStep(action="relaunched the browser", detail="restart " + str(self.restarts)))
        self._note("browser restarted (" + str(self.restarts) + ")")
        return RecoveryReport(
            kind="browser_crash",
            outcome="recovered",
            steps=steps,
            message="the browser was restarted",
            context={"restarts": self.restarts},
        )

    def ensure_logged_in(self, timeout_ms: int | None = None) -> RecoveryReport:
        """Re-open the page and wait for a manual sign-in when needed."""
        session = self.session
        steps: list[RecoveryStep] = []
        try:
            logged_in = bool(session.provider.is_logged_in())
        except Exception as exc:  # noqa: BLE001
            return RecoveryReport(
                kind="login_expired",
                outcome="failed",
                steps=[RecoveryStep(action="checked the login state", ok=False, detail=str(exc))],
                message="could not determine the login state",
            )

        if logged_in:
            return RecoveryReport(
                kind="login_expired",
                outcome="not_needed",
                steps=[RecoveryStep(action="login is valid")],
                message="still signed in",
            )

        steps.append(RecoveryStep(action="detected an expired login"))
        budget = self.login_timeout_ms if timeout_ms is None else timeout_ms
        try:
            session.provider.recover_session(timeout_ms=budget)
            ok = bool(session.provider.is_logged_in())
        except Exception as exc:  # noqa: BLE001
            return RecoveryReport(
                kind="login_expired",
                outcome="failed",
                steps=steps + [RecoveryStep(action="waited for a manual sign-in", ok=False, detail=str(exc))],
                message="the login was not restored within " + str(budget) + " ms",
            )

        steps.append(
            RecoveryStep(
                action="waited for a manual sign-in",
                ok=ok,
                detail="timeout " + str(budget) + " ms",
            )
        )
        return RecoveryReport(
            kind="login_expired",
            outcome="recovered" if ok else "failed",
            steps=steps,
            message="signed in again" if ok else "still signed out",
        )

    def ensure_ready(self, timeout_ms: int | None = None) -> RecoveryReport:
        """Make the page usable again: restart if dead, then check the login."""
        # Starting the session for the first time is not a recovery: creating it
        # lazily here keeps the report honest.
        created = self._session is None
        if created:
            self.session

        if not self.is_alive():
            report = self.restart()
            if report.failed:
                return report
            restart_steps = report.steps
        else:
            restart_steps = [
                RecoveryStep(
                    action="browser session is alive",
                    detail="started it" if created else "already running",
                )
            ]

        login = self.ensure_logged_in(timeout_ms)
        steps = restart_steps + login.steps
        restarted = len(restart_steps) > 1
        if login.failed:
            outcome = "failed"
        elif login.recovered or restarted:
            outcome = "recovered"
        else:
            outcome = "not_needed"
        return RecoveryReport(
            kind="browser_crash" if restarted else "login_expired",
            outcome=outcome,  # type: ignore[arg-type]
            steps=steps,
            message=login.message if login.failed or login.recovered else "the browser is ready",
            context={"restarts": self.restarts, "login": login.outcome, "started": created},
        )

    def call(self, function: Callable[[BrowserSessionLike], Any], timeout_ms: int | None = None) -> tuple[Any, RecoveryReport]:
        """Run 'function(session)', recovering once if the browser died.

        The function is retried at most once: an endless retry loop around a
        page that keeps crashing would hide the failure instead of reporting it.
        """
        try:
            return function(self.session), RecoveryReport(
                kind="browser_crash", outcome="not_needed", message="no recovery was needed"
            )
        except Exception as exc:  # noqa: BLE001 - the recovery decides
            first_error = exc

        report = self.ensure_ready(timeout_ms)
        if report.failed:
            report.message = (
                "the call failed (" + str(first_error) + ") and recovery did not help: " + report.message
            )
            return None, report

        try:
            return function(self.session), report
        except Exception as exc:  # noqa: BLE001
            return None, RecoveryReport(
                kind="browser_crash",
                outcome="failed",
                steps=report.steps + [RecoveryStep(action="retried the call", ok=False, detail=str(exc))],
                message="the call failed again after recovery: " + str(exc),
            )

    # -- teardown ----------------------------------------------------------

    def _close_quietly(self) -> None:
        if self._session is None:
            return
        try:
            self._session.close()
        except Exception:  # pragma: no cover - a dead session may refuse to close
            pass

    def close(self) -> None:
        self._close_quietly()
        self._session = None
