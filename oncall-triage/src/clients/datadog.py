import logging

from src.config import DatadogSettings
from src.models.metrics import MetricPoint, MetricSeries, MetricsQueryResult

from .base import BaseAsyncClient

logger = logging.getLogger(__name__)


class DatadogClient(BaseAsyncClient):
    """Client for Datadog Metrics Query API (v1)."""

    def __init__(self, settings: DatadogSettings):
        super().__init__(
            base_url=settings.base_url,
            headers={
                "DD-API-KEY": settings.api_key,
                "DD-APPLICATION-KEY": settings.app_key,
                "Content-Type": "application/json",
            },
        )
        self._settings = settings

    async def query_metrics(
        self,
        query: str,
        start_epoch: int,
        end_epoch: int,
    ) -> MetricsQueryResult:
        """Fetch metric timeseries from GET /api/v1/query.

        Args:
            query: Datadog metric query (e.g. from the alert's $ALERT_QUERY).
            start_epoch: POSIX timestamp for range start.
            end_epoch: POSIX timestamp for range end.
        """
        logger.info("Querying Datadog metrics: %s [%s -> %s]", query, start_epoch, end_epoch)
        data = await self._get(
            "/api/v1/query",
            params={"from": start_epoch, "to": end_epoch, "query": query},
        )

        series: list[MetricSeries] = []
        for s in data.get("series", []):
            unit_list = s.get("unit")
            unit_name = None
            if unit_list and isinstance(unit_list, list) and len(unit_list) > 0:
                unit_name = unit_list[0].get("name") if isinstance(unit_list[0], dict) else None

            series.append(
                MetricSeries(
                    metric=s.get("metric", ""),
                    display_name=s.get("display_name", s.get("metric", "")),
                    scope=s.get("scope", ""),
                    expression=s.get("expression", ""),
                    points=[
                        MetricPoint(timestamp=int(p[0]), value=p[1])
                        for p in s.get("pointlist", [])
                    ],
                    unit=unit_name,
                )
            )

        return MetricsQueryResult(
            query=query,
            series=series,
            from_date=start_epoch,
            to_date=end_epoch,
            status=data.get("status", "ok"),
        )
