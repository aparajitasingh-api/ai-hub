import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from src.models.webhook import DatadogWebhookPayload
from src.services.triage import TriageOrchestrator

from .dependencies import get_triage_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook/datadog", status_code=202)
async def handle_datadog_webhook(
    payload: DatadogWebhookPayload,
    background_tasks: BackgroundTasks,
    orchestrator: TriageOrchestrator = Depends(get_triage_orchestrator),
):
    """Receive Datadog alert webhooks.

    Returns 202 immediately; triage runs in the background.
    Only processes 'Triggered' and 'Re-Triggered' transitions.
    """
    transition = payload.alert_transition.lower()
    if transition not in ("triggered", "re-triggered"):
        logger.info(
            "Skipping non-trigger alert: id=%s transition=%s",
            payload.alert_id,
            payload.alert_transition,
        )
        return {"status": "skipped", "reason": f"transition '{payload.alert_transition}' ignored"}

    logger.info(
        "Accepted alert: id=%s title=%s",
        payload.alert_id,
        payload.alert_title,
    )
    background_tasks.add_task(orchestrator.handle_alert, payload)

    return {
        "status": "accepted",
        "alert_id": payload.alert_id,
        "message": "Triage initiated",
    }


@router.get("/health")
async def health_check():
    return {"status": "healthy"}
