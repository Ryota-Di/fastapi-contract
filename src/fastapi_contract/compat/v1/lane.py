"""Fixed legacy composition, with no current extractor or rule registration.

The delegated modules remain at their published import paths. Their algorithms
are legacy-owned and guarded by tests/unit/test_legacy_lane.py; implement current
semantics in the current lane instead of changing these dependencies in place.
"""

from fastapi import FastAPI

from fastapi_contract.adapters.fastapi import FastApiSnapshotExtractor
from fastapi_contract.application.checker import CheckResult, ContractChecker
from fastapi_contract.compat.v1.model import ContractSnapshot
from fastapi_contract.rules.fapi001 import Fapi001ResponseProjectionRule


class LegacyLane:
    """Extract and compare v1 snapshots using only the frozen legacy rule set."""

    def extract(self, app: FastAPI) -> ContractSnapshot:
        return FastApiSnapshotExtractor().extract(app)

    def check(self, baseline: ContractSnapshot, current: ContractSnapshot) -> CheckResult:
        return ContractChecker(rules=(Fapi001ResponseProjectionRule(),)).check(baseline, current)
