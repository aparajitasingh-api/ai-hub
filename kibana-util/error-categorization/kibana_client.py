"""
Kibana-backed Elasticsearch search client.

Proxies ES search queries through Kibana's /internal/bsearch API,
providing the same interface as elasticsearch-py's Elasticsearch.search().
"""

import json
import logging
import os
from typing import Optional

import requests
from elasticsearch import Elasticsearch, ElasticsearchException

logger = logging.getLogger(__name__)


class KibanaSearchException(ElasticsearchException):
    """Raised when a Kibana-proxied search fails."""
    pass


class KibanaSearchClient:
    """Drop-in replacement for Elasticsearch client, routing queries through Kibana's bsearch API."""

    BSEARCH_ENDPOINT = "/internal/bsearch"
    RESOLVE_INDEX_ENDPOINT = "/internal/index-pattern-management/resolve_index/{pattern}"
    SAVED_OBJECTS_ENDPOINT = "/api/saved_objects/_find"

    LOGIN_ENDPOINT = "/internal/security/login"

    def __init__(self, kibana_url: str, username: str = None, password: str = None, timeout: int = 60):
        self.base_url = kibana_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "kbn-xsrf": "true",
            "Content-Type": "application/json",
        })
        user = username or os.getenv("KIBANA_USERNAME")
        pw = password or os.getenv("KIBANA_PASSWORD")
        if user and pw:
            self.session.auth = (user, pw)
        else:
            self._guest_login()

    def _guest_login(self):
        """Authenticate via Kibana's anonymous/guest login and store the session cookie."""
        url = f"{self.base_url}{self.LOGIN_ENDPOINT}"
        payload = {
            "providerType": "anonymous",
            "providerName": "anonymous1",
            "currentURL": "/",
        }
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            logger.info("Kibana guest login successful")
        except requests.RequestException as e:
            raise KibanaSearchException(f"Kibana guest login failed: {e}") from e

    def search(self, index: str, body: dict) -> dict:
        """Execute an ES search query via Kibana's bsearch API. Returns standard ES response dict."""
        url = f"{self.base_url}{self.BSEARCH_ENDPOINT}"
        payload = {
            "batch": [{
                "request": {
                    "params": {
                        "index": index,
                        "body": body,
                        "wait_for_completion_timeout": f"{self.timeout}s",
                    }
                },
            }]
        }

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise KibanaSearchException(f"Kibana bsearch request failed: {e}") from e

        # bsearch may return NDJSON (one JSON object per line) or plain JSON
        text = resp.text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # NDJSON: parse the first line
            first_line = text.split("\n")[0]
            data = json.loads(first_line)

        # Unwrap the bsearch response envelope
        raw_response = (
            data.get("result", {}).get("rawResponse")
            or data.get("rawResponse")
            or data
        )
        return raw_response

    def resolve_indices(self, pattern: str = "*") -> list[str]:
        """Discover available index names matching a pattern."""
        url = f"{self.base_url}{self.RESOLVE_INDEX_ENDPOINT.format(pattern=pattern)}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return sorted(idx["name"] for idx in data.get("indices", []))
        except requests.RequestException as e:
            raise KibanaSearchException(f"Index resolution failed: {e}") from e

    def list_index_patterns(self) -> list[dict]:
        """List saved index patterns configured in Kibana."""
        url = f"{self.base_url}{self.SAVED_OBJECTS_ENDPOINT}"
        params = {"type": "index-pattern", "per_page": 100}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return [
                {"id": obj["id"], "title": obj["attributes"]["title"]}
                for obj in data.get("saved_objects", [])
            ]
        except requests.RequestException as e:
            raise KibanaSearchException(f"Index pattern listing failed: {e}") from e


def create_search_client(kibana_url: Optional[str] = None, es_host: Optional[str] = None,
                         kibana_username: Optional[str] = None, kibana_password: Optional[str] = None):
    """Factory: create the appropriate search client based on configuration."""
    kibana = kibana_url or os.getenv("KIBANA_URL")
    if kibana:
        logger.info("Using Kibana proxy at %s", kibana)
        return KibanaSearchClient(kibana, username=kibana_username, password=kibana_password)
    host = es_host or os.getenv("ES_HOST", "http://localhost:9200")
    return Elasticsearch([host])
