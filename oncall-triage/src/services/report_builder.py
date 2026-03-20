import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.models.alert import NormalizedAlert
from src.models.logs import LogSearchResult
from src.models.metrics import MetricsQueryResult
from src.models.report import TriageReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class ReportBuilder:
    """Builds a consolidated triage report from alert, metrics, and logs."""

    def __init__(self) -> None:
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
        )

    def build(
        self,
        alert: NormalizedAlert,
        metrics: MetricsQueryResult | None,
        logs: LogSearchResult | None,
    ) -> TriageReport:
        summary = self._generate_summary(alert, metrics, logs)
        rendered = self._render(alert, metrics, logs, summary)

        return TriageReport(
            alert=alert,
            metrics=metrics,
            logs=logs,
            generated_at=datetime.now(timezone.utc),
            summary=summary,
            rendered_text=rendered,
            datadog_dashboard_link=alert.datadog_link,
            kibana_discover_link=logs.kibana_link if logs else "",
        )

    def _generate_summary(
        self,
        alert: NormalizedAlert,
        metrics: MetricsQueryResult | None,
        logs: LogSearchResult | None,
    ) -> str:
        parts: list[str] = []

        parts.append(
            f"Alert '{alert.title}' {alert.transition.lower()} "
            f"at {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}."
        )

        if alert.service:
            parts.append(f"Affected service: {alert.service}.")
        if alert.hostname:
            parts.append(f"Host: {alert.hostname}.")

        if metrics and metrics.series:
            for s in metrics.series:
                peak = s.peak_value
                latest = s.latest_value
                unit = f" {s.unit}" if s.unit else ""
                if peak is not None:
                    parts.append(
                        f"Metric '{s.display_name}' peaked at {peak:.2f}{unit} "
                        f"(latest: {latest:.2f}{unit} if latest is not None else 'N/A')."
                    )
        else:
            parts.append("Metric data was unavailable.")

        if logs:
            error_count = len(logs.error_entries)
            parts.append(
                f"Found {logs.total_hits} log entries "
                f"({error_count} error-level) in the alert window."
            )
            unique_errors = logs.unique_error_messages
            if unique_errors:
                parts.append(
                    f"Top error: {unique_errors[0][:150]}"
                )
        else:
            parts.append("Log data was unavailable.")

        return " ".join(parts)

    def _render(
        self,
        alert: NormalizedAlert,
        metrics: MetricsQueryResult | None,
        logs: LogSearchResult | None,
        summary: str,
    ) -> str:
        template = self._jinja_env.get_template("report.md.j2")
        return template.render(
            alert=alert,
            metrics=metrics,
            logs=logs,
            summary=summary,
        )
