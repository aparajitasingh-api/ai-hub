import asyncio
import logging
from datetime import datetime, timezone

from src.clients.datadog import DatadogClient
from src.clients.elasticsearch import ElasticsearchClient
from src.clients.google_chat import GoogleChatClient
from src.config import AppSettings
from src.models.alert import NormalizedAlert
from src.models.webhook import DatadogWebhookPayload
from src.services.rca_agent import RCAAgent
from src.services.report_builder import ReportBuilder

logger = logging.getLogger(__name__)


class TriageOrchestrator:
    """Orchestrates the full triage pipeline:

    1. Normalize the webhook payload
    2. Fetch metrics and logs concurrently
    3. Build a consolidated report
    4. Post the report to Google Chat
    5. Run RCA analysis
    6. Post RCA to the same Chat thread
    """

    def __init__(
        self,
        settings: AppSettings,
        datadog: DatadogClient,
        elasticsearch: ElasticsearchClient,
        google_chat: GoogleChatClient,
        report_builder: ReportBuilder,
        rca_agent: RCAAgent,
    ) -> None:
        self._settings = settings
        self._dd = datadog
        self._es = elasticsearch
        self._chat = google_chat
        self._report_builder = report_builder
        self._rca = rca_agent

    async def handle_alert(self, payload: DatadogWebhookPayload) -> None:
        logger.info(
            "Processing alert: id=%s title=%s transition=%s",
            payload.alert_id,
            payload.alert_title,
            payload.alert_transition,
        )

        # Step 1: Normalize
        alert = self._normalize(payload)

        # Step 2+3: Fetch metrics and logs concurrently
        metrics_result, logs_result = await asyncio.gather(
            self._fetch_metrics(alert),
            self._fetch_logs(alert),
            return_exceptions=True,
        )

        metrics = None if isinstance(metrics_result, BaseException) else metrics_result
        logs = None if isinstance(logs_result, BaseException) else logs_result

        if isinstance(metrics_result, BaseException):
            logger.error("Failed to fetch metrics: %s", metrics_result, exc_info=metrics_result)
        if isinstance(logs_result, BaseException):
            logger.error("Failed to fetch logs: %s", logs_result, exc_info=logs_result)

        # Step 4: Build report
        report = self._report_builder.build(alert, metrics, logs)
        logger.info("Triage report built for alert %s", alert.alert_id)

        # Step 5: Post report to Google Chat
        thread_key = f"alert-{alert.alert_id}"
        try:
            await self._chat.post_report(report.rendered_text, thread_key)
            logger.info("Posted triage report to Google Chat")
        except Exception:
            logger.exception("Failed to post triage report to Google Chat")

        # Step 6+7: RCA analysis and posting
        try:
            rca = await self._rca.analyze(report)
            await self._chat.post_rca(rca.rendered_text, thread_key)
            logger.info("Posted RCA analysis to Google Chat")
        except Exception:
            logger.exception("RCA analysis or posting failed")

    def _normalize(self, payload: DatadogWebhookPayload) -> NormalizedAlert:
        # Parse timestamp: Datadog sends epoch seconds as a string
        try:
            epoch = int(payload.date)
            ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            ts = datetime.now(timezone.utc)

        return NormalizedAlert(
            alert_id=payload.alert_id,
            title=payload.alert_title,
            metric=payload.alert_metric,
            query=payload.alert_query,
            transition=payload.alert_transition,
            scope=payload.alert_scope,
            status_summary=payload.alert_status,
            hostname=payload.hostname,
            service=payload.service_name,
            tags=payload.tags_list,
            timestamp=ts,
            datadog_link=payload.link,
            snapshot_url=payload.snapshot,
            event_message=payload.event_msg,
            org_id=payload.org_id,
            window_minutes=self._settings.metric_window_minutes,
        )

    async def _fetch_metrics(self, alert: NormalizedAlert):
        start = int(alert.metric_window_start.timestamp())
        end = int(alert.metric_window_end.timestamp())
        return await self._dd.query_metrics(alert.query, start, end)

    async def _fetch_logs(self, alert: NormalizedAlert):
        start_iso = alert.metric_window_start.isoformat()
        end_iso = alert.metric_window_end.isoformat()
        return await self._es.search_logs(
            service=alert.service,
            hostname=alert.hostname,
            start_iso=start_iso,
            end_iso=end_iso,
            max_results=self._settings.max_log_results,
        )
