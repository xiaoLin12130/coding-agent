"""Provider command line (M9).

    cd backend
    python -m app.providers.cli list
    python -m app.providers.cli show openai_compatible
    python -m app.providers.cli check scripted --option plan=plan.json
    python -m app.providers.cli check openai_compatible \
        --option base_url=http://127.0.0.1:8080/v1 --option model=local --prompt "hi"

'check' builds the model and, with --prompt, asks it one question. Without
--prompt it only proves the provider can be constructed from those options, so
a configuration mistake is reported before a run starts instead of halfway in.
"""

from __future__ import annotations

import argparse
import json
import sys

from .models import ProviderError
from .registry import default_registry


def _options(pairs: list[str] | None) -> dict[str, str]:
    options: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("--option needs key=value, got: " + pair)
        key, value = pair.split("=", 1)
        options[key.strip()] = value
    return options


def _cmd_list(args: argparse.Namespace) -> int:
    registry = default_registry()
    infos = registry.infos()
    if args.json:
        print(json.dumps([info.model_dump(mode="json") for info in infos], indent=2, ensure_ascii=False))
        return 0
    print(str(len(infos)) + " provider(s):")
    for info in infos:
        flags = []
        if info.requires_login:
            flags.append("login")
        if info.requires_network:
            flags.append("network")
        if not flags:
            flags.append("offline")
        print("  " + info.name.ljust(20) + info.kind.ljust(8) + "(" + ",".join(flags) + ")  " + info.label)
        if info.model_label:
            print("      reaches: " + info.model_label)
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        info = default_registry().get(args.name).info
    except ProviderError as exc:
        print("provider error: " + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(info.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return 0
    print(info.name + " - " + info.label)
    print("  kind            : " + info.kind)
    print("  reaches         : " + (info.model_label or "(unspecified)"))
    print("  requires login  : " + ("yes" if info.requires_login else "no"))
    print("  requires network: " + ("yes" if info.requires_network else "no"))
    if info.description:
        print("  about           : " + info.description)
    if info.options:
        print("  options:")
        for option in info.options:
            marks = []
            if option.required:
                marks.append("required")
            if option.secret:
                marks.append("secret")
            if option.default != "":
                marks.append("default " + option.default)
            suffix = ("  [" + ", ".join(marks) + "]") if marks else ""
            print("    " + option.name.ljust(16) + option.description + suffix)
    else:
        print("  options         : (none)")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    options = _options(args.option)
    registry = default_registry()
    try:
        model = registry.create(args.name, **options)
    except ProviderError as exc:
        print("provider error: " + str(exc), file=sys.stderr)
        return 2
    report = {
        "provider": args.name,
        "kind": registry.get(args.name).info.kind,
        "model": getattr(model, "name", args.name),
        "options": sorted(options),
        "built": True,
        "answered": None,
        "error": None,
    }
    code = 0
    if args.prompt:
        try:
            from ..agents.llm import ModelClientError

            reply = model.complete(args.prompt)
            report["answered"] = reply.text[:400]
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report["error"] = type(exc).__name__ + ": " + str(exc)
            code = 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("provider : " + report["provider"] + " (" + report["kind"] + ")")
        print("model    : " + str(report["model"]))
        print("options  : " + (", ".join(report["options"]) or "(none)"))
        if args.prompt:
            if report["error"]:
                print("reply    : FAILED - " + str(report["error"]))
            else:
                print("reply    : " + str(report["answered"]).replace("\n", " ")[:200])
        else:
            print("reply    : not requested (pass --prompt to ask the model)")
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.providers.cli",
        description="Inspect and exercise the registered model providers.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="show every registered provider")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=_cmd_list)

    show = sub.add_parser("show", help="show one provider and its options")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=_cmd_show)

    check = sub.add_parser("check", help="build a provider from options (and optionally ask it)")
    check.add_argument("name")
    check.add_argument("--option", action="append", help="key=value, repeatable")
    check.add_argument("--prompt", default="", help="ask the model one question")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
