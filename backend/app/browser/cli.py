"""Command line entry points for the browser layer.

    cd backend
    python -m app.browser.cli profiles
    python -m app.browser.cli fixture --port 8765          # offline demo page
    python -m app.browser.cli inspect --profile mock
    python -m app.browser.cli login   --profile example-web-llm
    python -m app.browser.cli ask     --profile mock --prompt "hello"

The browser is always headed; sign-in is always manual.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import ArtifactStore
from .driver import BrowserDriver
from .errors import BrowserError
from .profiles import list_profiles, load_profile
from .web_chat import WebChatProvider


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, help="profile name or path")
    parser.add_argument("--url", default=None, help="override the profile URL")
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="persistent browser profile directory (default <repo>/.browser-profile)",
    )
    parser.add_argument(
        "--artifacts-dir", default=None, help="artifact base directory (default <repo>/runs)"
    )
    parser.add_argument(
        "--profiles-dir", default=None, help="directory holding profile JSON files"
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")


def _build_provider(args: argparse.Namespace) -> tuple[BrowserDriver, WebChatProvider]:
    profile = load_profile(args.profile, args.profiles_dir)
    if args.url:
        profile = profile.model_copy(update={"url": args.url})
    store = ArtifactStore(
        base_dir=args.artifacts_dir,
        run_name=f"{profile.name}",
    )
    driver = BrowserDriver(
        profile_dir=args.profile_dir, artifacts=store, headless=False
    ).start()
    return driver, WebChatProvider(driver, profile)


def _cmd_profiles(args: argparse.Namespace) -> int:
    names = list_profiles(args.profiles_dir)
    if args.json:
        print(json.dumps({"profiles": names}))
    else:
        for name in names:
            profile = load_profile(name, args.profiles_dir)
            mark = "verified" if profile.verified else "UNVERIFIED"
            print(f"{name:24} [{mark}] {profile.url}")
    return 0


def _cmd_fixture(args: argparse.Namespace) -> int:
    from fixtures.chat_site.server import main as fixture_main

    sys.argv = ["fixtures.chat_site.server", "--host", args.host, "--port", str(args.port)]
    return fixture_main()


def _cmd_inspect(args: argparse.Namespace) -> int:
    driver, provider = _build_provider(args)
    try:
        provider.open()
        snapshot = driver.dom_snapshot(label=f"{provider.name}-inspect")
        screenshot = driver.screenshot(label=f"{provider.name}-inspect")
        payload = {
            "run_dir": str(driver.artifacts.run_dir),
            "logged_in": provider.is_logged_in(),
            "url": snapshot.url,
            "title": snapshot.title,
            "html_path": snapshot.html_path,
            "text_path": snapshot.text_path,
            "screenshot": str(screenshot),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    finally:
        driver.close()


def _cmd_login(args: argparse.Namespace) -> int:
    driver, provider = _build_provider(args)
    try:
        ok = provider.recover_session(timeout_ms=args.timeout * 1000)
        payload = {"logged_in": ok, "url": driver.page_url()}
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else payload)
        return 0 if ok else 1
    finally:
        driver.close()


def _cmd_ask(args: argparse.Namespace) -> int:
    driver, provider = _build_provider(args)
    try:
        provider.open()
        reply = provider.ask(args.prompt, timeout_ms=args.timeout * 1000)
        payload = reply.model_dump(mode="json")
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"source   : {reply.source}")
            print(f"completed: {reply.completed} (timed_out={reply.timed_out})")
            print(f"reply    : {reply.text}")
            print(f"artifacts: {reply.artifacts.run_dir}")
            for path in reply.artifacts.all_paths():
                print(f"  - {path}")
        if not reply.completed:
            print("warning: generation did not complete before the timeout", file=sys.stderr)
            return 2
        return 0
    finally:
        driver.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.browser.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_profiles = sub.add_parser("profiles", help="list provider profiles")
    p_profiles.add_argument("--profiles-dir", default=None)
    p_profiles.add_argument("--json", action="store_true")
    p_profiles.set_defaults(func=_cmd_profiles)

    p_fixture = sub.add_parser("fixture", help="serve the offline fixture chat page")
    p_fixture.add_argument("--host", default="127.0.0.1")
    p_fixture.add_argument("--port", type=int, default=8765)
    p_fixture.set_defaults(func=_cmd_fixture)

    p_inspect = sub.add_parser("inspect", help="open a profile and dump the DOM")
    _add_common(p_inspect)
    p_inspect.set_defaults(func=_cmd_inspect)

    p_login = sub.add_parser("login", help="open a profile and wait for a manual login")
    _add_common(p_login)
    p_login.add_argument("--timeout", type=int, default=300, help="seconds to wait")
    p_login.set_defaults(func=_cmd_login)

    p_ask = sub.add_parser("ask", help="send a prompt and capture the reply")
    _add_common(p_ask)
    p_ask.add_argument("--prompt", required=True)
    p_ask.add_argument("--timeout", type=int, default=120, help="seconds to wait")
    p_ask.set_defaults(func=_cmd_ask)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except BrowserError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
