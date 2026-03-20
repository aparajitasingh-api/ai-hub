from src.models.webhook import DatadogWebhookPayload


def test_parse_webhook_payload(raw_webhook_payload):
    payload = DatadogWebhookPayload.model_validate(raw_webhook_payload)

    assert payload.alert_id == "12345678"
    assert payload.alert_title == "[P1] CPU idle critically low on web-01"
    assert payload.alert_transition == "Triggered"
    assert payload.hostname == "web-01"
    assert payload.date == "1710864000"


def test_tags_list(webhook_payload):
    tags = webhook_payload.tags_list
    assert "service:payment-api" in tags
    assert "env:production" in tags
    assert len(tags) == 3


def test_service_name(webhook_payload):
    assert webhook_payload.service_name == "payment-api"


def test_service_name_missing():
    payload = DatadogWebhookPayload(
        alert_id="1",
        alert_title="test",
        alert_transition="Triggered",
        date="0",
        tags="env:prod,team:infra",
    )
    assert payload.service_name is None


def test_payload_with_python_field_names():
    """Verify payload works with both alias (ALERT_ID) and field name (alert_id)."""
    payload = DatadogWebhookPayload(
        alert_id="abc",
        alert_title="test title",
        alert_transition="Triggered",
        date="123",
    )
    assert payload.alert_id == "abc"
    assert payload.alert_title == "test title"
