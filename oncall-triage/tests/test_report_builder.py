from src.services.report_builder import ReportBuilder


def test_build_report_full(normalized_alert, sample_metrics, sample_logs):
    builder = ReportBuilder()
    report = builder.build(normalized_alert, sample_metrics, sample_logs)

    assert report.alert.alert_id == "12345678"
    assert report.metrics is not None
    assert report.logs is not None
    assert "ONCALL TRIAGE REPORT" in report.rendered_text
    assert "payment-api" in report.rendered_text
    assert report.summary != ""
    assert report.datadog_dashboard_link != ""
    assert report.kibana_discover_link != ""


def test_build_report_no_metrics(normalized_alert, sample_logs):
    builder = ReportBuilder()
    report = builder.build(normalized_alert, None, sample_logs)

    assert report.metrics is None
    assert "unavailable" in report.rendered_text.lower() or "unavailable" in report.summary.lower()


def test_build_report_no_logs(normalized_alert, sample_metrics):
    builder = ReportBuilder()
    report = builder.build(normalized_alert, sample_metrics, None)

    assert report.logs is None
    assert report.kibana_discover_link == ""


def test_build_report_nothing(normalized_alert):
    builder = ReportBuilder()
    report = builder.build(normalized_alert, None, None)

    assert report.metrics is None
    assert report.logs is None
    assert "ONCALL TRIAGE REPORT" in report.rendered_text
