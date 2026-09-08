"""Keyed route correspondence and fail-closed status aggregation."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fastapi_contract.domain.finding import CompatibilityImpact, Finding
from fastapi_contract.domain.model import ContractSnapshot, RouteContract, RouteMatchKey


class CheckStatus(StrEnum):
    SAFE = "SAFE"
    REVIEW = "REVIEW"
    BREAKING = "BREAKING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AnalysisError:
    code: str
    message: str


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    findings: tuple[Finding, ...] = ()
    error: AnalysisError | None = None


class Rule(Protocol):
    def check(self, before: RouteContract, after: RouteContract) -> tuple[Finding, ...]: ...


def _index(snapshot: ContractSnapshot) -> dict[RouteMatchKey, RouteContract]:
    index: dict[RouteMatchKey, RouteContract] = {}
    for item in snapshot.application.routes:
        route = item.contract
        if route.match_key in index:
            raise ValueError(f"Duplicate runtime route identity: {route.match_key}")
        index[route.match_key] = route
    return index


class ContractChecker:
    def __init__(self, rules: tuple[Rule, ...]) -> None:
        self.rules = rules

    def check(self, baseline: ContractSnapshot, current: ContractSnapshot) -> CheckResult:
        if baseline.metadata.schema_version != 1 or current.metadata.schema_version != 1:
            return CheckResult(
                CheckStatus.ERROR,
                error=AnalysisError(
                    "INCOMPATIBLE_SCHEMA", "Only snapshot schema version 1 is supported"
                ),
            )
        if baseline.metadata.environment != current.metadata.environment:
            return CheckResult(
                CheckStatus.ERROR,
                error=AnalysisError(
                    "INCOMPATIBLE_ENVIRONMENT", "Snapshot framework or Python versions differ"
                ),
            )
        try:
            old, new = _index(baseline), _index(current)
        except ValueError as exc:
            return CheckResult(
                CheckStatus.ERROR, error=AnalysisError("AMBIGUOUS_ROUTE_IDENTITY", str(exc))
            )
        try:
            findings = tuple(
                finding
                for key, route in old.items()
                if key in new
                for rule in self.rules
                for finding in rule.check(route, new[key])
            )
        except Exception as exc:
            return CheckResult(CheckStatus.ERROR, error=AnalysisError("ANALYSIS_FAILED", str(exc)))
        findings = tuple(sorted(findings, key=lambda f: (f.route, f.rule_id, f.impact.value)))
        if any(f.impact is CompatibilityImpact.INCOMPATIBLE for f in findings):
            status = CheckStatus.BREAKING
        elif findings:
            status = CheckStatus.REVIEW
        else:
            status = CheckStatus.SAFE
        return CheckResult(status, findings)
