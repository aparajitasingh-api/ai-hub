import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BaseAsyncClient:
    """Base class for all external service clients.

    Manages an httpx.AsyncClient with connection pooling,
    configurable timeouts, and exponential-backoff retries.
    """

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self._base_url = base_url
        self._default_headers = headers or {}
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._default_headers,
            timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                f"{self.__class__.__name__} not started. Call start() first."
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self.client.request(method, path, **kwargs)
                if resp.status_code >= 500 and attempt < self._max_retries:
                    logger.warning(
                        "Server error %s on %s %s (attempt %d/%d)",
                        resp.status_code,
                        method,
                        path,
                        attempt,
                        self._max_retries,
                    )
                    await asyncio.sleep(2**attempt * 0.5)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning(
                    "Transport error on %s %s (attempt %d/%d): %s",
                    method,
                    path,
                    attempt,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt * 0.5)

        raise RuntimeError(
            f"Request {method} {path} failed after {self._max_retries} retries"
        ) from last_exc

    async def _get(self, path: str, params: dict | None = None) -> dict:
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def _post(self, path: str, json: dict | None = None) -> dict:
        resp = await self._request("POST", path, json=json)
        return resp.json()
