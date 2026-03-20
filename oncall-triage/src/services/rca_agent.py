import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.clients.github import GitHubClient
from src.models.rca import CodeReference, RCAAnalysis
from src.models.report import TriageReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class RCAAgent:
    """Root Cause Analysis agent.

    Given a TriageReport, this agent:
    1. Extracts error patterns and anomalies
    2. Searches GitHub for related code
    3. Correlates findings to produce an RCA

    Designed as a standalone module -- depends only on
    a TriageReport and a GitHubClient.
    """

    def __init__(self, github_client: GitHubClient) -> None:
        self._github = github_client
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
        )

    async def analyze(self, report: TriageReport) -> RCAAnalysis:
        logger.info("Starting RCA analysis for alert %s", report.alert.alert_id)

        signals = self._extract_signals(report)
        code_refs = await self._fetch_code_references(signals)
        analysis = self._correlate(report, signals, code_refs)
        analysis.rendered_text = self._render(analysis)

        logger.info(
            "RCA complete: confidence=%s, evidence=%d, refs=%d",
            analysis.confidence,
            len(analysis.evidence),
            len(analysis.code_references),
        )
        return analysis

    def _extract_signals(self, report: TriageReport) -> dict:
        """Extract actionable signals from the triage report."""
        error_patterns: list[str] = []
        stack_traces: list[str] = []

        if report.logs:
            for entry in report.logs.entries:
                if entry.level.lower() in ("error", "fatal", "critical"):
                    error_patterns.append(entry.message)
                if "Traceback" in entry.message or "Exception" in entry.message:
                    stack_traces.append(entry.message)

        # Deduplicate, keep order
        seen: set[str] = set()
        unique_errors: list[str] = []
        for msg in error_patterns:
            key = msg[:120]
            if key not in seen:
                seen.add(key)
                unique_errors.append(msg)

        return {
            "error_patterns": unique_errors[:10],
            "stack_traces": stack_traces[:5],
            "metric_name": report.alert.metric,
            "service": report.alert.service,
            "hostname": report.alert.hostname,
        }

    async def _fetch_code_references(
        self,
        signals: dict,
    ) -> list[CodeReference]:
        try:
            return await self._github.find_relevant_code(
                metric_name=signals["metric_name"],
                service_name=signals["service"],
                error_patterns=signals["error_patterns"][:3],
            )
        except Exception:
            logger.exception("Failed to fetch code references from GitHub")
            return []

    def _correlate(
        self,
        report: TriageReport,
        signals: dict,
        code_refs: list[CodeReference],
    ) -> RCAAnalysis:
        evidence: list[str] = []
        suggested_actions: list[str] = []
        confidence = "low"

        # Heuristic 1: Match error patterns against code snippets
        for ref in code_refs:
            for pattern in signals["error_patterns"]:
                keywords = [w for w in pattern.split()[:5] if len(w) > 4]
                matches = [k for k in keywords if k in ref.snippet]
                if matches:
                    evidence.append(
                        f"Error pattern matches code in {ref.repo}/{ref.file_path} "
                        f"(matched: {', '.join(matches[:3])})"
                    )
                    confidence = "medium"

        # Heuristic 2: Metric name found in code
        for ref in code_refs:
            if signals["metric_name"] and signals["metric_name"] in ref.snippet:
                evidence.append(
                    f"Metric '{signals['metric_name']}' is emitted from "
                    f"{ref.repo}/{ref.file_path}"
                )
                if confidence == "low":
                    confidence = "medium"

        # Heuristic 3: Stack trace function names in code
        for trace in signals.get("stack_traces", []):
            # Extract potential function/class names from stack traces
            for word in trace.split():
                if "." in word and not word.startswith("http"):
                    func_name = word.split(".")[-1].rstrip("():,")
                    if len(func_name) > 3:
                        for ref in code_refs:
                            if func_name in ref.snippet:
                                evidence.append(
                                    f"Stack trace function '{func_name}' found in "
                                    f"{ref.repo}/{ref.file_path}"
                                )
                                confidence = "high"
                                break

        # Deduplicate evidence
        evidence = list(dict.fromkeys(evidence))

        # Build probable cause
        if evidence:
            probable_cause = (
                f"Based on {len(evidence)} evidence point(s), the issue "
                f"is correlated with code in the affected service's "
                f"error handling or metric emission paths. "
                f"Review the referenced files for recent changes."
            )
            suggested_actions = [
                "Review the referenced code files for recent commits",
                "Check deployment history for the affected service around the alert time",
                "Examine error patterns in logs for upstream dependency failures",
                "Verify configuration and environment variable changes",
            ]
        else:
            probable_cause = (
                "Automated analysis could not determine a specific root cause. "
                "Manual investigation is recommended. Consider checking: "
                "recent deployments, infrastructure changes, and upstream dependencies."
            )
            suggested_actions = [
                "Check recent deployments to the affected service",
                "Review infrastructure metrics (CPU, memory, disk, network)",
                "Check upstream dependency health",
                "Review recent configuration or secret changes",
            ]

        return RCAAnalysis(
            alert_id=report.alert.alert_id,
            probable_cause=probable_cause,
            confidence=confidence,
            evidence=evidence,
            code_references=code_refs,
            suggested_actions=suggested_actions,
        )

    def _render(self, analysis: RCAAnalysis) -> str:
        template = self._jinja_env.get_template("rca.md.j2")
        return template.render(analysis=analysis)
