import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models.alert import NormalizedAlert
from src.models.logs import LogEntry, LogSearchResult
from src.models.metrics import MetricPoint, MetricSeries, MetricsQueryResult
from src.models.report import TriageReport
from src.models.webhook import DatadogWebhookPayload

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_webhook_payload() -> dict:
    return json.loads((FIXTURES_DIR / "datadog_webhook.json").read_text())


@pytest.fixture
def webhook_payload(raw_webhook_payload) -> DatadogWebhookPayload:
    return DatadogWebhookPayload.model_validate(raw_webhook_payload)


@pytest.fixture
def normalized_alert() -> NormalizedAlert:
    return NormalizedAlert(
        alert_id="12345678",
        title="[P1] CPU idle critically low on web-01",
        metric="avg:system.cpu.idle{host:web-01}",
        query="avg(last_5m):avg:system.cpu.idle{host:web-01} < 10",
        transition="Triggered",
        scope="host:web-01",
        status_summary="CPU idle has dropped below 10%",
        hostname="web-01",
        service="payment-api",
        tags=["service:payment-api", "env:production", "team:platform"],
        timestamp=datetime(2024, 3, 19, 16, 0, 0, tzinfo=timezone.utc),
        datadog_link="https://app.datadoghq.com/monitors/12345678",
        snapshot_url="https://p.datadoghq.com/snapshot/abc123.png",
        event_message="CPU idle dropped below threshold.",
        org_id="99999",
        window_minutes=10,
    )


@pytest.fixture
def sample_metrics() -> MetricsQueryResult:
    return MetricsQueryResult(
        query="avg(last_5m):avg:system.cpu.idle{host:web-01} < 10",
        series=[
            MetricSeries(
                metric="system.cpu.idle",
                display_name="system.cpu.idle",
                scope="host:web-01",
                expression="avg:system.cpu.idle{host:web-01}",
                points=[
                    MetricPoint(timestamp=1710863400, value=45.0),
                    MetricPoint(timestamp=1710863700, value=30.0),
                    MetricPoint(timestamp=1710864000, value=8.5),
                    MetricPoint(timestamp=1710864300, value=5.2),
                    MetricPoint(timestamp=1710864600, value=12.0),
                ],
                unit="percent",
            )
        ],
        from_date=1710863400,
        to_date=1710864600,
        status="ok",
    )


@pytest.fixture
def sample_logs() -> LogSearchResult:
    return LogSearchResult(
        total_hits=42,
        entries=[
            LogEntry(
                timestamp="2024-03-19T16:00:01Z",
                level="error",
                message="Connection pool exhausted for payment-gateway upstream",
                service="payment-api",
                host="web-01",
            ),
            LogEntry(
                timestamp="2024-03-19T15:59:55Z",
                level="error",
                message="Timeout waiting for response from payment-gateway: Traceback in PaymentClient.process_payment",
                service="payment-api",
                host="web-01",
            ),
            LogEntry(
                timestamp="2024-03-19T15:59:50Z",
                level="warning",
                message="Retry attempt 3/3 for payment-gateway request",
                service="payment-api",
                host="web-01",
            ),
            LogEntry(
                timestamp="2024-03-19T15:59:30Z",
                level="info",
                message="Health check passed",
                service="payment-api",
                host="web-01",
            ),
        ],
        query_used={"query": {"bool": {"must": []}}},
        kibana_link="https://kibana.example.com/app/discover#/?_g=...",
    )


@pytest.fixture
def sample_report(normalized_alert, sample_metrics, sample_logs) -> TriageReport:
    return TriageReport(
        alert=normalized_alert,
        metrics=sample_metrics,
        logs=sample_logs,
        generated_at=datetime(2024, 3, 19, 16, 1, 0, tzinfo=timezone.utc),
        summary="Alert triggered. CPU idle dropped. 42 log entries found.",
        rendered_text="(rendered report text)",
        datadog_dashboard_link="https://app.datadoghq.com/monitors/12345678",
        kibana_discover_link="https://kibana.example.com/app/discover#/?_g=...",
    )
