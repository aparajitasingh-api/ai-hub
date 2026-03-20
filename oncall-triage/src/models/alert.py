from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, computed_field


class NormalizedAlert(BaseModel):
    alert_id: str
    title: str
    metric: str
    query: str
    transition: str
    scope: str
    status_summary: str
    hostname: str
    service: str | None
    tags: list[str]
    timestamp: datetime
    datadog_link: str
    snapshot_url: str
    event_message: str
    org_id: str
    window_minutes: int = 10

    @computed_field
    @property
    def metric_window_start(self) -> datetime:
        return self.timestamp - timedelta(minutes=self.window_minutes)

    @computed_field
    @property
    def metric_window_end(self) -> datetime:
        return self.timestamp + timedelta(minutes=self.window_minutes)
