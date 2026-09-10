"""Current canonical checker; version dispatch belongs to the transport boundary."""

from fastapi_contract.application.checker import AnalysisError, CheckResult, CheckStatus
from fastapi_contract.domain.facts import CanonicalSnapshot, RouteFacts
from fastapi_contract.domain.finding import CompatibilityImpact
from fastapi_contract.domain.finding_order import finding_sort_key
from fastapi_contract.domain.model import RouteMatchKey
from fastapi_contract.rules.body_binding import BodyBindingRule
from fastapi_contract.rules.parameter_binding import ParameterBindingRule
from fastapi_contract.rules.parameter_requirement import ParameterRequirementRule
from fastapi_contract.rules.response_surface import ResponseSurfaceRule


def _index(snapshot: CanonicalSnapshot) -> dict[RouteMatchKey, RouteFacts]:
    result = {}
    for route in snapshot.routes:
        if route.match_key in result:
            raise ValueError("Duplicate runtime route identity")
        result[route.match_key] = route
    return result


class ContractFactChecker:
    def check(self, baseline: CanonicalSnapshot, current: CanonicalSnapshot) -> CheckResult:
        if baseline.environment != current.environment:
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
            response_rule = ResponseSurfaceRule()
            body_rule = BodyBindingRule()
            binding_rule = ParameterBindingRule()
            requirement_rule = ParameterRequirementRule()
            findings = tuple(
                f
                for key in sorted(old.keys() & new.keys())
                for f in (
                    *response_rule.check(old[key], new[key]),
                    *body_rule.check(old[key], new[key]),
                    *binding_rule.check(old[key], new[key]),
                    *requirement_rule.check(old[key], new[key]),
                )
            )
        except Exception as exc:
            return CheckResult(CheckStatus.ERROR, error=AnalysisError("ANALYSIS_FAILED", str(exc)))
        status = CheckStatus.SAFE
        if findings:
            status = CheckStatus.REVIEW
        if any(f.impact is CompatibilityImpact.INCOMPATIBLE for f in findings):
            status = CheckStatus.BREAKING
        return CheckResult(status, tuple(sorted(findings, key=finding_sort_key)))


ResponseFactChecker = ContractFactChecker
