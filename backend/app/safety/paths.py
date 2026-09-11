"""Filesystem policy: nothing outside the project, nothing sensitive.

docs/safety.md:

* default allow: the project working directory
* forbidden: paths outside the project, system directories, SSH private keys,
  credentials and other secrets

Resolution happens on the RESOLVED path (symlinks followed), so a symlink
cannot be used to step outside the project.
"""

from __future__ import annotations

import os
from pathlib import Path

from .models import PathDecision
from .policy import SafetyPolicy


def _norm(path: Path) -> str:
    return os.path.normcase(str(path))


def is_within(child: Path, parent: Path) -> bool:
    child_text = _norm(child)
    parent_text = _norm(parent)
    if child_text == parent_text:
        return True
    return child_text.startswith(parent_text.rstrip(os.sep) + os.sep)


class FilesystemPolicy:
    def __init__(self, policy: SafetyPolicy) -> None:
        self.policy = policy

    # -- classification ----------------------------------------------------

    def sensitive_label(self, path: Path) -> str | None:
        """Why this path is sensitive, or None when it is not."""
        for part in path.parts:
            lowered = part.lower()
            if lowered in self.policy.sensitive_directories:
                return "sensitive directory " + part
            if lowered in self.policy.sensitive_names:
                return "credential-style file " + part
        if path.suffix and path.suffix.lower() in self.policy.sensitive_suffixes:
            return "key material (" + path.suffix.lower() + ")"
        return None

    def sensitive_reference(self, text: str) -> str | None:
        """Detect a sensitive file mentioned inside free text (e.g. a command)."""
        lowered = text.lower().replace("\\", "/")
        for name in sorted(self.policy.sensitive_names):
            if name.lower() in lowered:
                return "references " + name
        for directory in sorted(self.policy.sensitive_directories):
            if directory.lower() + "/" in lowered:
                return "references " + directory
        for suffix in sorted(self.policy.sensitive_suffixes):
            marker = suffix.lower()
            if marker + " " in lowered or marker in ("",):
                continue
            if lowered.rstrip().endswith(marker):
                return "references key material " + suffix
        return None

    # -- the check ---------------------------------------------------------

    def resolve(self, path: str | Path, base: Path | None = None) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (base or self.policy.project_root) / candidate
        # Follow symlinks so they cannot be used to escape the project.
        try:
            return candidate.resolve()
        except OSError:
            return candidate.absolute()

    def check(self, path: str | Path, base: Path | None = None) -> PathDecision:
        resolved = self.resolve(path, base)
        roots = self.policy.roots()
        inside = any(is_within(resolved, root) for root in roots)
        sensitive = self.sensitive_label(resolved)

        if sensitive is not None:
            return PathDecision(
                allowed=False,
                reason="refused: " + sensitive,
                requested=str(path),
                resolved=str(resolved),
                inside_project=inside,
                sensitive=sensitive,
            )
        if not inside:
            return PathDecision(
                allowed=False,
                reason="refused: outside the project working directory",
                requested=str(path),
                resolved=str(resolved),
                inside_project=False,
            )
        return PathDecision(
            allowed=True,
            reason="inside the project",
            requested=str(path),
            resolved=str(resolved),
            inside_project=True,
        )

    def outside_paths_in(self, text: str, base: Path | None = None) -> list[str]:
        """Absolute-looking paths in free text that escape the project."""
        found: list[str] = []
        for token in _candidate_paths(text):
            resolved = self.resolve(token, base)
            if not any(is_within(resolved, root) for root in self.policy.roots()):
                found.append(token)
        return found


def _candidate_paths(text: str) -> list[str]:
    """Pull path-looking tokens out of a shell command, conservatively."""
    import re

    tokens: list[str] = []
    for match in re.finditer(r"""[^\s'"|;&<>]+""", text):
        token = match.group(0)
        looks_absolute = (
            re.match(r"^[A-Za-z]:[\\/]", token)
            or token.startswith("/")
            or token.startswith("~")
            or token.startswith("..")
        )
        if looks_absolute:
            tokens.append(token)
    return tokens


def build_filesystem_policy(project_root: Path, extra_roots: list[Path] | None = None) -> FilesystemPolicy:
    return FilesystemPolicy(
        SafetyPolicy(project_root=project_root, extra_roots=list(extra_roots or []))
    )
