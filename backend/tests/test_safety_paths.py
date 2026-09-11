"""Filesystem policy tests: scope, escapes, sensitive files, symlinks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.safety import FilesystemPolicy, SafetyPolicy, is_within


@pytest.fixture()
def policy(tmp_path: Path) -> SafetyPolicy:
    project = tmp_path / "project"
    project.mkdir()
    return SafetyPolicy(project_root=project)


@pytest.fixture()
def fs(policy: SafetyPolicy) -> FilesystemPolicy:
    return FilesystemPolicy(policy)


def test_relative_path_inside_the_project_is_allowed(fs, policy) -> None:
    (policy.project_root / "src").mkdir()
    (policy.project_root / "src" / "a.py").write_text("x", encoding="utf-8")

    decision = fs.check("src/a.py")

    assert decision.allowed is True
    assert decision.inside_project is True
    assert decision.sensitive is None


def test_the_project_root_itself_is_allowed(fs, policy) -> None:
    assert fs.check(".").allowed is True


def test_absolute_path_outside_the_project_is_refused(fs, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    decision = fs.check(str(outside))

    assert decision.allowed is False
    assert "outside the project" in decision.reason
    assert decision.inside_project is False


def test_relative_escape_is_refused(fs, policy) -> None:
    decision = fs.check("../outside.txt")
    assert decision.allowed is False


def test_deep_relative_escape_is_refused(fs, policy) -> None:
    decision = fs.check("a/b/../../../outside.txt")
    assert decision.allowed is False


def test_sibling_directory_with_a_shared_prefix_is_refused(fs, tmp_path) -> None:
    # /tmp/project-evil must not pass because it starts with /tmp/project
    sibling = Path(str(fs.policy.project_root) + "-evil")
    sibling.mkdir()

    assert fs.check(str(sibling)).allowed is False


def test_empty_path_resolves_to_the_project(fs, policy) -> None:
    assert fs.check("").allowed is True


@pytest.mark.parametrize(
    "name",
    [".env", "id_rsa", "id_ed25519", ".npmrc", ".netrc", "credentials", "auth.json"],
)
def test_sensitive_names_are_refused_inside_the_project(fs, policy, name: str) -> None:
    (policy.project_root / name).write_text("secret", encoding="utf-8")

    decision = fs.check(name)

    assert decision.allowed is False
    assert decision.sensitive is not None


@pytest.mark.parametrize("suffix", [".pem", ".key", ".pfx", ".p12", ".keystore"])
def test_key_material_suffixes_are_refused(fs, policy, suffix: str) -> None:
    (policy.project_root / ("server" + suffix)).write_text("secret", encoding="utf-8")

    decision = fs.check("server" + suffix)

    assert decision.allowed is False
    assert "key material" in (decision.sensitive or "")


@pytest.mark.parametrize("directory", [".ssh", ".aws", ".gnupg"])
def test_sensitive_directories_are_refused(fs, policy, directory: str) -> None:
    (policy.project_root / directory).mkdir()
    (policy.project_root / directory / "thing").write_text("secret", encoding="utf-8")

    decision = fs.check(directory + "/thing")

    assert decision.allowed is False
    assert "sensitive directory" in (decision.sensitive or "")


def test_sensitive_check_beats_inside_project(fs, policy) -> None:
    """Being inside the project does not excuse a credential file."""
    nested = policy.project_root / "config"
    nested.mkdir()
    (nested / ".env").write_text("x", encoding="utf-8")

    decision = fs.check("config/.env")

    assert decision.allowed is False
    assert decision.inside_project is True


def test_extra_roots_are_allowed(fs, policy, tmp_path) -> None:
    extra = tmp_path / "shared"
    extra.mkdir()
    (extra / "a.txt").write_text("x", encoding="utf-8")
    policy.extra_roots = [extra]

    assert FilesystemPolicy(policy).check(extra / "a.txt").allowed is True


def test_symlink_escape_is_refused(fs, policy, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = policy.project_root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    decision = fs.check("link.txt")

    assert decision.allowed is False, "a symlink must not be a way out of the project"


def test_symlink_inside_the_project_is_allowed(fs, policy) -> None:
    (policy.project_root / "real.txt").write_text("x", encoding="utf-8")
    link = policy.project_root / "alias.txt"
    try:
        link.symlink_to(policy.project_root / "real.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    assert fs.check("alias.txt").allowed is True


def test_outside_paths_are_listed_for_a_command(fs, policy, tmp_path) -> None:
    outside = tmp_path / "elsewhere" / "file.txt"

    found = fs.outside_paths_in("cat " + str(outside))

    assert found and str(outside) in found[0]


def test_inside_paths_are_not_listed(fs, policy) -> None:
    inside = policy.project_root / "src" / "a.py"

    assert fs.outside_paths_in("cat " + str(inside)) == []


def test_sensitive_reference_detects_mentions_in_text(fs) -> None:
    assert fs.sensitive_reference("cat ~/.ssh/id_rsa") is not None
    assert fs.sensitive_reference("cat ./src/main.py") is None


def test_is_within_handles_equality_and_prefixes(tmp_path) -> None:
    root = tmp_path / "p"
    root.mkdir()

    assert is_within(root, root) is True
    assert is_within(root / "a", root) is True
    assert is_within(tmp_path / "other", root) is False


def test_case_insensitive_comparison_on_windows(fs, policy) -> None:
    if os.name != "nt":
        pytest.skip("case-insensitive paths are a Windows behaviour")
    upper = str(policy.project_root).upper()
    assert fs.check(upper).allowed is True


def test_build_filesystem_policy_helper(tmp_path) -> None:
    built = FilesystemPolicy(SafetyPolicy(project_root=tmp_path))
    assert built.policy.project_root == tmp_path
