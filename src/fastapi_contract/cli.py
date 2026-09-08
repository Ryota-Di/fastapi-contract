"""Snapshot-file CLI and CI exit contract for the FAPI001 technical preview."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fastapi_contract.adapters.fastapi import FastApiSnapshotExtractor
from fastapi_contract.app_loader import load_app
from fastapi_contract.application.checker import CheckResult, CheckStatus, ContractChecker
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec
from fastapi_contract.reporting.text import TextReporter
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


def exit_code_for(result: CheckResult) -> int:
    return {
        CheckStatus.SAFE: 0,
        CheckStatus.BREAKING: 1,
        CheckStatus.REVIEW: 1,
        CheckStatus.ERROR: 2,
    }[result.status]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fastapi-contract", description="Check FastAPI response projection compatibility."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Save an app's response contract as JSON")
    snapshot.add_argument("app", help="FastAPI instance as module:attribute")
    snapshot.add_argument("-o", "--output", required=True, type=Path)
    check = commands.add_parser("check", help="Compare an app against a saved snapshot")
    check.add_argument("app", help="FastAPI instance as module:attribute")
    check.add_argument("--against", required=True, type=Path)
    args = parser.parse_args(argv)
    codec = CanonicalJsonSnapshotCodec()
    extractor = FastApiSnapshotExtractor()
    try:
        if args.command == "snapshot":
            current = extractor.extract(load_app(args.app))
            args.output.write_text(codec.encode(current), encoding="utf-8")
            return 0
        baseline = codec.decode(args.against.read_text(encoding="utf-8"))
        current = extractor.extract(load_app(args.app))
        result = ContractChecker(rules=(Fapi001ResponseProjectionRule(),)).check(baseline, current)
        print(TextReporter().render(result))
        return exit_code_for(result)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
