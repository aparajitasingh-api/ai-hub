from pydantic import BaseModel, Field


class DatadogWebhookPayload(BaseModel):
    """Incoming Datadog webhook payload.

    Field aliases match Datadog's template variable names (without $).
    Configure the Datadog webhook to send JSON with these keys.
    """

    model_config = {"populate_by_name": True}

    alert_id: str = Field("", alias="ALERT_ID")
    alert_metric: str = Field("", alias="ALERT_METRIC")
    alert_query: str = Field("", alias="ALERT_QUERY")
    alert_title: str = Field("", alias="ALERT_TITLE")
    alert_transition: str = Field("", alias="ALERT_TRANSITION")
    alert_scope: str = Field("", alias="ALERT_SCOPE")
    alert_status: str = Field("", alias="ALERT_STATUS")
    alert_type: str = Field("", alias="ALERT_TYPE")
    hostname: str = Field("", alias="HOSTNAME")
    tags: str = Field("", alias="TAGS")
    date: str = Field("", alias="DATE")
    link: str = Field("", alias="LINK")
    snapshot: str = Field("", alias="SNAPSHOT")
    event_msg: str = Field("", alias="EVENT_MSG")
    org_id: str = Field("", alias="ORG_ID")
    priority: str = Field("", alias="PRIORITY")

    @property
    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def service_name(self) -> str | None:
        for tag in self.tags_list:
            if tag.startswith("service:"):
                return tag.split(":", 1)[1]
        return None
