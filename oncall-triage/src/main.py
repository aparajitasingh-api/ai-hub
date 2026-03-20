import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.dependencies import get_settings, set_orchestrator
from src.api.router import router
from src.clients.datadog import DatadogClient
from src.clients.elasticsearch import ElasticsearchClient
from src.clients.github import GitHubClient
from src.clients.google_chat import GoogleChatClient
from src.logging_config import setup_logging
from src.services.rca_agent import RCAAgent
from src.services.report_builder import ReportBuilder
from src.services.triage import TriageOrchestrator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting oncall-triage agent")

    # Initialize clients
    dd_client = DatadogClient(settings.datadog)
    es_client = ElasticsearchClient(settings.elasticsearch)
    chat_client = GoogleChatClient(settings.google_chat)
    gh_client = GitHubClient(settings.github)

    await dd_client.start()
    await es_client.start()
    await chat_client.start()
    await gh_client.start()

    # Wire up services
    report_builder = ReportBuilder()
    rca_agent = RCAAgent(gh_client)
    orchestrator = TriageOrchestrator(
        settings=settings,
        datadog=dd_client,
        elasticsearch=es_client,
        google_chat=chat_client,
        report_builder=report_builder,
        rca_agent=rca_agent,
    )
    set_orchestrator(orchestrator)

    logger.info("All clients initialized, ready to receive webhooks")
    yield

    # Shutdown
    logger.info("Shutting down oncall-triage agent")
    await dd_client.close()
    await es_client.close()
    await chat_client.close()
    await gh_client.close()


app = FastAPI(
    title="Oncall Triage Agent",
    description="Automated oncall alert triaging with RCA analysis",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
