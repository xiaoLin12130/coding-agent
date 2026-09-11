"""CLI smoke tests (no real network, no real LLM)."""

from __future__ import annotations

import json
from pathlib import Path

from app.browser import cli
from tests.conftest import PROFILES_DIR, make_driver  # noqa: F401  (fixtures used)


def test_profiles_command_lists_mock(capsys) -> None:
    exit_code = cli.main(["profiles", "--profiles-dir", str(PROFILES_DIR), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "mock" in payload["profiles"]


def test_ask_command_runs_the_acceptance_path(capsys, fixture_site, tmp_path: Path) -> None:
    exit_code = cli.main(
        [
            "ask",
            "--profile",
            "mock",
            "--profiles-dir",
            str(PROFILES_DIR),
            "--url",
            fixture_site.base_url,
            "--prompt",
            "cli check",
            "--timeout",
            "30",
            "--profile-dir",
            str(tmp_path / "cli-profile"),
            "--artifacts-dir",
            str(tmp_path / "runs"),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["completed"] is True
    assert payload["text"] == "Fixture reply to: cli check"
    assert payload["artifacts"]["screenshots"]
    assert Path(payload["artifacts"]["screenshots"][0]).exists()
    assert Path(payload["artifacts"]["dom_snapshots"][0]).exists()


def test_ask_command_reports_timeout_with_exit_code_2(
    capsys, fixture_site, tmp_path: Path
) -> None:
    exit_code = cli.main(
        [
            "ask",
            "--profile",
            "mock",
            "--profiles-dir",
            str(PROFILES_DIR),
            "--url",
            f"{fixture_site.base_url}?mode=stuck",
            "--prompt",
            "stuck check",
            "--timeout",
            "3",
            "--profile-dir",
            str(tmp_path / "cli-profile"),
            "--artifacts-dir",
            str(tmp_path / "runs"),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(captured.out)
    assert payload["completed"] is False
    assert payload["timed_out"] is True
    assert "did not complete" in captured.err


def test_inspect_command_saves_dom_and_screenshot(
    capsys, fixture_site, tmp_path: Path
) -> None:
    exit_code = cli.main(
        [
            "inspect",
            "--profile",
            "mock",
            "--profiles-dir",
            str(PROFILES_DIR),
            "--url",
            fixture_site.base_url,
            "--profile-dir",
            str(tmp_path / "cli-profile"),
            "--artifacts-dir",
            str(tmp_path / "runs"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["logged_in"] is True
    assert Path(payload["html_path"]).exists()
    assert Path(payload["screenshot"]).exists()


def test_unknown_profile_returns_error_code(capsys, tmp_path: Path) -> None:
    exit_code = cli.main(["inspect", "--profile", "missing-profile", "--profiles-dir", str(tmp_path)])

    assert exit_code == 1
    assert "profile_error" in capsys.readouterr().err
