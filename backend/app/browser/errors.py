"""Browser / provider errors.

Every error carries a machine-readable 'code' so the future API layer can
map failures onto protocol error frames without parsing messages.
"""

from __future__ import annotations


class BrowserError(RuntimeError):
    code = "browser_error"


class BrowserConfigError(BrowserError):
    """The driver was configured in a way M1 forbids (e.g. headless)."""

    code = "browser_config_error"


class ProfileError(BrowserError):
    """A provider profile is missing or invalid."""

    code = "profile_error"


class ProviderError(BrowserError):
    """The provider could not perform an operation on the page."""

    code = "provider_error"


class LoginRequiredError(ProviderError):
    """The page shows a login wall.

    Recovery is manual by design: log in inside the headed browser window.
    This project does not automate credentials, captcha or risk-control flows.
    """

    code = "login_required"
