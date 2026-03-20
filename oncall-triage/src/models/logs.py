from typing import Any

from pydantic import BaseModel


class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    service: str | None = None
    host: str | None = None
    trace_id: str | None = None
    raw: dict[str, Any] = {}


class LogSearchResult(BaseModel):
    total_hits: int
    entries: list[LogEntry]
    query_used: dict[str, Any]
    kibana_link: str

    @property
    def error_entries(self) -> list[LogEntry]:
        return [
            e
            for e in self.entries
            if e.level.lower() in ("error", "fatal", "critical")
        ]

    @property
    def unique_error_messages(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for e in self.error_entries:
            key = e.message[:120]
            if key not in seen:
                seen.add(key)
                result.append(e.message)
        return result
