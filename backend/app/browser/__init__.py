"""Browser layer (M1).

Playwright-driven, headed, persistent-profile browser automation plus the one
ProviderAdapter implementation used to drive a web chat page.

Deliberately NOT implemented here (later milestones): Tool layer,
SafetyLayer, Executor, AgentLoop, multi-agent orchestration and automatic
context switching.

Everything read out of a page (DOM text, network bodies) is DATA; it is
returned as validated models and never interpreted as instructions.
"""

from .artifacts import ArtifactStore
from .driver import BrowserDriver
from .errors import (
    BrowserConfigError,
    BrowserError,
    LoginRequiredError,
    ProfileError,
    ProviderError,
)
from .models import (
    BrowserArtifacts,
    CapturedText,
    CompletionPolicy,
    CompletionTimeline,
    DomSnapshot,
    ProviderProfile,
    ProviderReply,
)
from .profiles import list_profiles, load_profile, profiles_dir, save_profile
from .provider import ProviderAdapter
from .web_chat import WebChatProvider

__all__ = [
    "ArtifactStore",
    "BrowserArtifacts",
    "BrowserConfigError",
    "BrowserDriver",
    "BrowserError",
    "CapturedText",
    "CompletionPolicy",
    "CompletionTimeline",
    "DomSnapshot",
    "LoginRequiredError",
    "ProfileError",
    "ProviderAdapter",
    "ProviderError",
    "ProviderProfile",
    "ProviderReply",
    "WebChatProvider",
    "list_profiles",
    "load_profile",
    "profiles_dir",
    "save_profile",
]
