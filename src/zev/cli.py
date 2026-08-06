"""Top-level command line interface for zev."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zev import setup
from zev.bridge import BridgeError, execute_js


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zev",
        description="Evaluate JavaScript inside a running Zotero, and manage the bridge plugin.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Print the installed zev version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")

    eval_parser = subparsers.add_parser(
        "eval",
        help="Evaluate JavaScript in Zotero's privileged context.",
        description=(
            "The code is a bare statement body ending in `return JSON.stringify(...)`; "
            "the plugin supplies the async wrapper, so do not add your own."
        ),
    )
    eval_parser.add_argument(
        "file",
        nargs="?",
        help="Path to a .js file. Reads stdin when omitted.",
    )
    eval_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the bridge envelope instead of just the returned value.",
    )
    eval_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for Zotero (default: 60).",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Run non-mutating setup diagnostics.")
    doctor_parser.add_argument(
        "--no-network",
        action="store_true",
        help="Skip checks that call GitHub release metadata.",
    )

    setup_parser = subparsers.add_parser("setup", help="Guide Zotero bridge setup or upgrade.")
    setup_parser.add_argument(
        "--check",
        action="store_true",
        help="Run setup diagnostics without making changes.",
    )
    setup_parser.add_argument(
        "--download-only",
        action="store_true",
        help="Print the XPI path to use and do not install.",
    )
    setup_parser.add_argument(
        "--force",
        action="store_true",
        help="Show install guidance even when the bridge appears current.",
    )
    setup_parser.add_argument(
        "--install-profile",
        action="store_true",
        help="Copy the XPI into the default Zotero profile. Zotero must be closed.",
    )
    setup_parser.add_argument(
        "--xpi",
        help="Use a local zev-bridge.xpi instead of the bundled artifact.",
    )
    setup_parser.add_argument(
        "--no-network",
        action="store_true",
        help="Only use bundled artifacts and local checks.",
    )
    return parser


def _run_eval(args: argparse.Namespace) -> int:
    code = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    if not code.strip():
        print("zev: no JavaScript supplied", file=sys.stderr)
        return 2

    try:
        body = execute_js(code, timeout=args.timeout)
    except BridgeError as exc:
        print(f"zev: {exc}", file=sys.stderr)
        return 1

    if args.raw:
        print(json.dumps(body, indent=2))
        return 0

    # `return JSON.stringify(...)` is the documented contract, so unwrap it when
    # it holds; anything else is passed through untouched rather than guessed at.
    result = body.get("result")
    if isinstance(result, str):
        try:
            print(json.dumps(json.loads(result), indent=2))
            return 0
        except json.JSONDecodeError:
            print(result)
            return 0
    print(json.dumps(result, indent=2))
    return 0


def _run_doctor(no_network: bool = False) -> int:
    result = setup.run_doctor(no_network=no_network)
    print(setup.format_doctor(result))
    return 0 if result.ready else 1


def _run_setup(args: argparse.Namespace) -> int:
    try:
        xpi_path = setup.resolve_setup_xpi(args.xpi)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.download_only:
        print(xpi_path)
        return 0

    result = setup.run_doctor(no_network=args.no_network)
    if args.check:
        print(setup.format_doctor(result))
        return 0 if result.ready else 1

    if args.install_profile:
        try:
            destination = setup.install_bridge_into_profile(xpi_path)
        except (FileNotFoundError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Installed zev-bridge to {destination}")
        print("Restart Zotero, then run `zev doctor` to verify the bridge.")
        return 0

    print(setup.setup_guidance(xpi_path, result, force=args.force))
    return 0 if result.ready else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.version:
        print(f"zev {setup.package_version()}")
        return 0

    if args.command == "eval":
        return _run_eval(args)
    if args.command == "doctor":
        return _run_doctor(no_network=args.no_network)
    if args.command == "setup":
        return _run_setup(args)

    parser.print_help(sys.stderr)
    return 2
