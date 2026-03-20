from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppSettings
from src.models.metrics import MetricsQueryResult
from src.models.logs import LogSearchResult
from src.models.rca import RCAAnalysis
from src.models.report import TriageReport
from src.models.webhook import DatadogWebhookPayload
from src.services.triage import TriageOrchestrator


@pytest.fixture
def mock_settings():
    with patch.dict("os.environ", {}, clear=False):
        settings = MagicMock(spec=AppSettings)
        settings.metric_window_minutes = 10
        settings.max_log_results = 200
        return settings


@pytest.fixture
def mock_orchestrator(mock_settings):
    dd = AsyncMock()
    es = AsyncMock()
    chat = AsyncMock()
    report_builder = MagicMock()
    rca_agent = AsyncMock()

    orchestrator = TriageOrchestrator(
        settings=mock_settings,
        datadog=dd,
        elasticsearch=es,
        google_chat=chat,
        report_builder=report_builder,
        rca_agent=rca_agent,
    )
    return orchestrator, dd, es, chat, report_builder, rca_agent


@pytest.mark.asyncio
async def test_handle_alert_full_pipeline(mock_orchestrator, sample_metrics, sample_logs, sample_report):
    orchestrator, dd, es, chat, report_builder, rca_agent = mock_orchestrator

    dd.query_metrics.return_value = sample_metrics
    es.search_logs.return_value = sample_logs
    report_builder.build.return_value = sample_report
    rca_agent.analyze.return_value = RCAAnalysis(
        alert_id="12345678",
        probable_cause="Test cause",
        confidence="medium",
        evidence=["test evidence"],
        code_references=[],
        suggested_actions=["check logs"],
        rendered_text="RCA text",
    )
    chat.post_report.return_value = {}
    chat.post_rca.return_value = {}

    payload = DatadogWebhookPayload(
        alert_id="12345678",
        alert_title="[P1] CPU idle critically low on web-01",
        alert_transition="Triggered",
        date="1710864000",
        tags="service:payment-api,env:production",
        hostname="web-01",
        alert_metric="avg:system.cpu.idle{host:web-01}",
        alert_query="avg(last_5m):avg:system.cpu.idle{host:web-01} < 10",
        link="https://app.datadoghq.com/monitors/12345678",
    )

    await orchestrator.handle_alert(payload)

    dd.query_metrics.assert_called_once()
    es.search_logs.assert_called_once()
    report_builder.build.assert_called_once()
    chat.post_report.assert_called_once()
    rca_agent.analyze.assert_called_once()
    chat.post_rca.assert_called_once()

    # Verify thread_key is based on alert_id
    report_call_args = chat.post_report.call_args
    assert "alert-12345678" in report_call_args.args or "alert-12345678" == report_call_args.args[1]


@pytest.mark.asyncio
async def test_handle_alert_metrics_failure(mock_orchestrator, sample_logs, sample_report):
    orchestrator, dd, es, chat, report_builder, rca_agent = mock_orchestrator

    dd.query_metrics.side_effect = RuntimeError("Datadog API unavailable")
    es.search_logs.return_value = sample_logs
    report_builder.build.return_value = sample_report
    rca_agent.analyze.return_value = RCAAnalysis(
        alert_id="test-001",
        probable_cause="Unknown",
        confidence="low",
        evidence=[],
        code_references=[],
        suggested_actions=[],
        rendered_text="RCA text",
    )
    chat.post_report.return_value = {}
    chat.post_rca.return_value = {}

    payload = DatadogWebhookPayload(
        alert_id="test-001",
        alert_title="Test Alert",
        alert_transition="Triggered",
        date="1710864000",
    )

    # Should not raise -- partial failure is handled gracefully
    await orchestrator.handle_alert(payload)

    # Report should still be built (with metrics=None)
    report_builder.build.assert_called_once()
    build_args = report_builder.build.call_args
    assert build_args.args[1] is None  # metrics is None
    chat.post_report.assert_called_once()
