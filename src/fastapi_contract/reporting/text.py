"""Actionable CI output with explicitly scoped SAFE wording."""

from fastapi_contract.application.checker import CheckResult, CheckStatus


class TextReporter:
    def render(self, result: CheckResult) -> str:
        if result.status is CheckStatus.ERROR:
            if result.error is None:
                return "ERROR: Missing analysis error details"
            return f"ERROR {result.error.code}: {result.error.message}"
        if result.status is CheckStatus.SAFE:
            return "SAFE: No incompatibility detected in the supported contract surface."
        lines = [result.status.value]
        for finding in result.findings:
            route = f"{finding.route.method} {finding.route.path}"
            if finding.evidence.reason:
                detail = f"reason: {finding.evidence.reason}"
            else:
                removed = ", ".join(
                    ".".join(path.segments) for path in finding.evidence.removed_fields
                )
                detail = f"response fields removed by projection: {removed}"
            lines.append(f"{finding.rule_id} {route}: {detail}")
        return "\n".join(lines)
