"""Provider profile loading.

Profiles are JSON files under backend/profiles (override with
CODING_AGENT_PROFILES_DIR). One profile describes one web chat page.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import profiles_dir as _default_profiles_dir
from .errors import ProfileError
from .models import ProviderProfile


def profiles_dir(directory: Path | str | None = None) -> Path:
    if directory is not None:
        return Path(directory)
    return _default_profiles_dir()


def resolve_profile_path(
    name_or_path: str, directory: Path | str | None = None
) -> Path:
    candidate = Path(name_or_path)
    if candidate.suffix == ".json":
        return candidate if candidate.is_absolute() else Path.cwd() / candidate
    return profiles_dir(directory) / f"{name_or_path}.json"


def load_profile(
    name_or_path: str, directory: Path | str | None = None
) -> ProviderProfile:
    """Load a profile by name (mock -> profiles/mock.json) or by path."""
    path = resolve_profile_path(name_or_path, directory)
    if not path.exists():
        raise ProfileError(f"provider profile not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"profile {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {path} must contain a JSON object")
    try:
        return ProviderProfile.model_validate(raw)
    except Exception as exc:
        raise ProfileError(f"profile {path} is invalid: {exc}") from exc


def list_profiles(directory: Path | str | None = None) -> list[str]:
    base = profiles_dir(directory)
    if not base.exists():
        return []
    return sorted(path.stem for path in base.glob("*.json"))


def save_profile(
    profile: ProviderProfile, directory: Path | str | None = None
) -> Path:
    base = profiles_dir(directory)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{profile.name}.json"
    path.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path
