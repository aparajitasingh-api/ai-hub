from functools import lru_cache

from src.config import AppSettings
from src.services.triage import TriageOrchestrator

_orchestrator: TriageOrchestrator | None = None


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


def set_orchestrator(orchestrator: TriageOrchestrator) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def get_triage_orchestrator() -> TriageOrchestrator:
    if _orchestrator is None:
        raise RuntimeError("TriageOrchestrator not initialized. App may not have started.")
    return _orchestrator
