from datetime import datetime

from pydantic import BaseModel

from .alert import NormalizedAlert
from .logs import LogSearchResult
from .metrics import MetricsQueryResult


class TriageReport(BaseModel):
    alert: NormalizedAlert
    metrics: MetricsQueryResult | None = None
    logs: LogSearchResult | None = None
    generated_at: datetime
    summary: str
    rendered_text: str
    datadog_dashboard_link: str
    kibana_discover_link: str
