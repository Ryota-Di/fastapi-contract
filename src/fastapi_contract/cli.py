"""Baseline-driven compatibility lanes and stable CI exit contract."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fastapi_contract.adapters.response import FastApiFactExtractor
from fastapi_contract.app_loader import load_app
from fastapi_contract.application.baseline_loader import LegacyBaseline, load_baseline
from fastapi_contract.application.checker import CheckResult, CheckStatus
from fastapi_contract.application.response import ContractFactChecker
from fastapi_contract.codec.json import CanonicalJsonSnapshotCodec
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec
from fastapi_contract.compat.v1.lane import LegacyLane
from fastapi_contract.reporting.notices import LEGACY_BASELINE_NOTICE
from fastapi_contract.reporting.text import TextReporter


def exit_code_for(result: CheckResult) -> int:
    return {
        CheckStatus.SAFE: 0,
        CheckStatus.BREAKING: 1,
        CheckStatus.REVIEW: 1,
        CheckStatus.ERROR: 2,
    }[result.status]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fastapi-contract",
        description="Check supported FastAPI response and input binding contracts.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Save an app's supported contract as JSON")
    snapshot.add_argument("app", help="FastAPI instance as module:attribute")
    snapshot.add_argument("-o", "--output", required=True, type=Path)
    snapshot.add_argument(
        "--schema-version",
        type=int,
        choices=(1, 2),
        default=2,
        help="2: current contracts (default); 1: legacy published format",
    )
    check = commands.add_parser("check", help="Compare an app against a saved snapshot")
    check.add_argument("app", help="FastAPI instance as module:attribute")
    check.add_argument("--against", required=True, type=Path)
    args = parser.parse_args(argv)
    codec = CanonicalJsonSnapshotCodec()
    legacy = LegacyLane()
    try:
        if args.command == "snapshot":
            if args.schema_version == 2:
                facts = FastApiFactExtractor().extract(load_app(args.app))
                args.output.write_text(SnapshotV2Codec().encode(facts), encoding="utf-8")
                return 0
            current = legacy.extract(load_app(args.app))
            args.output.write_text(codec.encode(current), encoding="utf-8")
            return 0
        baseline = load_baseline(args.against.read_text(encoding="utf-8"))
        if isinstance(baseline, LegacyBaseline):
            print(LEGACY_BASELINE_NOTICE, file=sys.stderr)
            current = legacy.extract(load_app(args.app))
            result = legacy.check(baseline.document, current)
        else:
            current_facts = FastApiFactExtractor().extract(load_app(args.app))
            result = ContractFactChecker().check(baseline.document.facts, current_facts)
        print(
            TextReporter().render(result),
            file=sys.stderr if result.status is CheckStatus.ERROR else sys.stdout,
        )
        return exit_code_for(result)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
