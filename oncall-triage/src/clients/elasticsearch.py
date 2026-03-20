import base64
import logging
from typing import Any
from urllib.parse import quote

from src.config import ElasticsearchSettings
from src.models.logs import LogEntry, LogSearchResult

from .base import BaseAsyncClient

logger = logging.getLogger(__name__)


class ElasticsearchClient(BaseAsyncClient):
    """Client for Elasticsearch log search via the _search API."""

    def __init__(self, settings: ElasticsearchSettings):
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"ApiKey {settings.api_key}"
        elif settings.username and settings.password:
            cred = base64.b64encode(
                f"{settings.username}:{settings.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {cred}"

        super().__init__(
            base_url=settings.hosts_list[0],
            headers=headers,
        )
        self._settings = settings

    async def search_logs(
        self,
        service: str | None,
        hostname: str | None,
        start_iso: str,
        end_iso: str,
        max_results: int = 200,
        extra_query: str | None = None,
    ) -> LogSearchResult:
        """Search for log entries in a time range for a given service.

        Builds an ES bool query with must clauses for time range,
        optional service and hostname filters.
        """
        logger.info(
            "Searching ES logs: service=%s host=%s [%s -> %s]",
            service,
            hostname,
            start_iso,
            end_iso,
        )

        must_clauses: list[dict[str, Any]] = [
            {"range": {"@timestamp": {"gte": start_iso, "lte": end_iso}}}
        ]
        if service:
            must_clauses.append({"term": {"service.name.keyword": service}})
        if hostname:
            must_clauses.append({"term": {"host.name.keyword": hostname}})
        if extra_query:
            must_clauses.append({"query_string": {"query": extra_query}})

        body = {
            "query": {"bool": {"must": must_clauses}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": max_results,
        }

        index = self._settings.index_pattern
        data = await self._post(f"/{index}/_search", json=body)

        entries: list[LogEntry] = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            entries.append(
                LogEntry(
                    timestamp=src.get("@timestamp", ""),
                    level=src.get("log.level", src.get("level", "unknown")),
                    message=src.get("message", ""),
                    service=src.get("service", {}).get("name")
                    if isinstance(src.get("service"), dict)
                    else src.get("service"),
                    host=src.get("host", {}).get("name")
                    if isinstance(src.get("host"), dict)
                    else src.get("host"),
                    trace_id=src.get("trace", {}).get("id")
                    if isinstance(src.get("trace"), dict)
                    else src.get("trace_id"),
                    raw=src,
                )
            )

        total = data.get("hits", {}).get("total", {})
        total_hits = total.get("value", 0) if isinstance(total, dict) else int(total)

        kibana_link = self._build_kibana_link(service, start_iso, end_iso)

        return LogSearchResult(
            total_hits=total_hits,
            entries=entries,
            query_used=body,
            kibana_link=kibana_link,
        )

    def _build_kibana_link(
        self,
        service: str | None,
        start: str,
        end: str,
    ) -> str:
        base = self._settings.kibana_base_url.rstrip("/")
        time_part = f"(time:(from:'{start}',to:'{end}'))"
        query_part = ""
        if service:
            query_part = f"(query:(language:kuery,query:'service.name:\"{service}\"'))"

        url = f"{base}/app/discover#/?_g={quote(time_part)}"
        if query_part:
            url += f"&_a={quote(query_part)}"
        return url
