"""Backend configuration.

Only what M0 needs: where the persisted state files live and the app metadata.
Paths stay configurable so tests can point them at a temporary directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "coding-agent-backend"
APP_VERSION = "0.1.0"

# backend/app/config.py -> backend/app -> backend -> <project root>
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent

ENV_PROJECT_ROOT = "CODING_AGENT_PROJECT_ROOT"
ENV_STATE_DIR = "CODING_AGENT_STATE_DIR"
ENV_RUNS_DIR = "CODING_AGENT_RUNS_DIR"
ENV_PROFILES_DIR = "CODING_AGENT_PROFILES_DIR"
ENV_BROWSER_PROFILE_DIR = "CODING_AGENT_BROWSER_PROFILE_DIR"
ENV_SESSIONS_DIR = "CODING_AGENT_SESSIONS_DIR"
ENV_CHECKPOINTS_DIR = "CODING_AGENT_CHECKPOINTS_DIR"


def project_root() -> Path:
    """Project root: the repository root that holds state/ and milestones/."""
    override = os.environ.get(ENV_PROJECT_ROOT)
    if override:
        return Path(override).resolve()
    return _PROJECT_ROOT


def state_dir() -> Path:
    """Directory holding project_state.json and memory.json."""
    override = os.environ.get(ENV_STATE_DIR)
    if override:
        return Path(override).resolve()
    return project_root() / "state"


def sessions_dir() -> Path:
    """Directory holding session transcripts and the session index."""
    override = os.environ.get(ENV_SESSIONS_DIR)
    if override:
        return Path(override).resolve()
    return state_dir() / "sessions"

def checkpoints_dir() -> Path:
    """Directory holding agent-run checkpoints."""
    override = os.environ.get(ENV_CHECKPOINTS_DIR)
    if override:
        return Path(override).resolve()
    return state_dir() / "checkpoints"


def runs_dir() -> Path:
    """Directory holding browser artifacts (screenshots, DOM snapshots)."""
    override = os.environ.get(ENV_RUNS_DIR)
    if override:
        return Path(override).resolve()
    return project_root() / "runs"


def profiles_dir() -> Path:
    """Directory holding provider profiles (shipped with the backend)."""
    override = os.environ.get(ENV_PROFILES_DIR)
    if override:
        return Path(override).resolve()
    return _BACKEND_DIR / "profiles"


def browser_profile_dir() -> Path:
    """Persistent browser user-data directory (cookies, localStorage, login)."""
    override = os.environ.get(ENV_BROWSER_PROFILE_DIR)
    if override:
        return Path(override).resolve()
    return project_root() / ".browser-profile"


@dataclass(frozen=True)
class AppPaths:
    project_root: Path
    state_dir: Path
    project_state_file: Path
    memory_file: Path


def get_paths() -> AppPaths:
    directory = state_dir()
    return AppPaths(
        project_root=project_root(),
        state_dir=directory,
        project_state_file=directory / "project_state.json",
        memory_file=directory / "memory.json",
    )