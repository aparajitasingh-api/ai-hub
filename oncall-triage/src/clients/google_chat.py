import logging

import httpx

from src.config import GoogleChatSettings

logger = logging.getLogger(__name__)


class GoogleChatClient:
    """Client for posting messages to Google Chat via incoming webhook.

    Supports threaded replies using threadKey. The webhook approach
    requires no OAuth setup -- just a webhook URL from the Chat space.
    """

    def __init__(self, settings: GoogleChatSettings):
        self._webhook_url = settings.webhook_url
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GoogleChatClient not started. Call start() first.")
        return self._client

    async def post_message(
        self,
        text: str,
        thread_key: str | None = None,
    ) -> dict:
        """Post a message to the configured Google Chat space.

        Args:
            text: Message text (supports Chat formatting).
            thread_key: Groups messages into a thread. Use the alert_id
                        so the report and RCA land in the same thread.
        """
        url = self._webhook_url
        body: dict = {"text": text}

        if thread_key:
            separator = "&" if "?" in url else "?"
            url += f"{separator}messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
            body["thread"] = {"threadKey": thread_key}

        logger.info("Posting to Google Chat (thread_key=%s)", thread_key)
        resp = await self.client.post(
            url,
            json=body,
            headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        resp.raise_for_status()
        return resp.json()

    async def post_report(self, text: str, thread_key: str) -> dict:
        """Post the triage report as the first message in a thread."""
        return await self.post_message(text, thread_key)

    async def post_rca(self, text: str, thread_key: str) -> dict:
        """Post the RCA analysis as a reply in the same thread."""
        return await self.post_message(text, thread_key)
