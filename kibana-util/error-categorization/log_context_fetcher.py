"""
Log context fetcher for Kibana/Elasticsearch.
Fetches surrounding log lines for a given error phrase to enrich RCA analysis.
"""

import argparse
import json
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from elasticsearch import ElasticsearchException

from error_categories import index_names
from kibana_client import KibanaSearchException, create_search_client

load_dotenv()

logger = logging.getLogger(__name__)

es = None  # initialized in main or by init_client()


def init_client(kibana_url: str = None, kibana_username: str = None, kibana_password: str = None):
    """Initialize the module-level ES client."""
    global es
    es = create_search_client(kibana_url=kibana_url, kibana_username=kibana_username,
                              kibana_password=kibana_password)

DEFAULT_CONTEXT_LINES = 30


# ---------------------------------------------------------------------------
# ES queries
# ---------------------------------------------------------------------------

def _find_error_entries(index: str, container: str, error_phrase: str,
                        start: datetime, end: datetime, count: int = 2) -> list[dict]:
    """Find error log entries matching the phrase. Returns up to `count` hits."""
    query = {
        "size": count,
        "_source": ["message", "@timestamp"],
        "sort": [{"@timestamp": "desc"}],
        "query": {
            "bool": {
                "filter": [
                    {"term": {"kubernetes.container.name.keyword": container}},
                    {"match_phrase": {"message": error_phrase}},
                    {"range": {"@timestamp": {
                        "gte": start.isoformat(),
                        "lte": end.isoformat(),
                        "format": "strict_date_optional_time"
                    }}},
                ]
            }
        }
    }
    try:
        resp = es.search(index=index, body=query)
    except (ElasticsearchException, KibanaSearchException) as e:
        logger.warning("ES query failed finding error entries: %s", e)
        return []
    return [
        {"message": h["_source"]["message"], "timestamp": h["_source"]["@timestamp"]}
        for h in resp["hits"]["hits"]
    ]


def _fetch_surrounding(index: str, container: str, timestamp: str,
                       context_lines: int) -> dict:
    """Fetch log lines before and after a given timestamp from the same container."""
    base_filter = [
        {"term": {"kubernetes.container.name.keyword": container}},
    ]

    # Lines before (including the target timestamp)
    before_query = {
        "size": context_lines,
        "_source": ["message", "@timestamp"],
        "sort": [{"@timestamp": "desc"}],
        "query": {
            "bool": {
                "filter": base_filter + [
                    {"range": {"@timestamp": {"lte": timestamp, "format": "strict_date_optional_time"}}}
                ]
            }
        }
    }

    # Lines after (including the target timestamp)
    after_query = {
        "size": context_lines,
        "_source": ["message", "@timestamp"],
        "sort": [{"@timestamp": "asc"}],
        "query": {
            "bool": {
                "filter": base_filter + [
                    {"range": {"@timestamp": {"gte": timestamp, "format": "strict_date_optional_time"}}}
                ]
            }
        }
    }

    before_lines = []
    after_lines = []

    try:
        resp = es.search(index=index, body=before_query)
        before_lines = [
            {"ts": h["_source"]["@timestamp"], "msg": h["_source"]["message"]}
            for h in resp["hits"]["hits"]
        ]
        before_lines.reverse()  # chronological order
    except (ElasticsearchException, KibanaSearchException) as e:
        logger.warning("ES query failed fetching before-context: %s", e)

    try:
        resp = es.search(index=index, body=after_query)
        after_lines = [
            {"ts": h["_source"]["@timestamp"], "msg": h["_source"]["message"]}
            for h in resp["hits"]["hits"]
        ]
    except (ElasticsearchException, KibanaSearchException) as e:
        logger.warning("ES query failed fetching after-context: %s", e)

    # Merge and deduplicate by timestamp+message
    seen = set()
    merged = []
    for line in before_lines + after_lines:
        key = (line["ts"], line["msg"][:200])
        if key not in seen:
            seen.add(key)
            merged.append(line)

    # Sort chronologically
    merged.sort(key=lambda x: x["ts"])

    return {
        "lines": merged,
        "context_text": "\n".join(l["msg"] for l in merged),
    }


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def fetch_log_context(
    container: str,
    error_phrase: str,
    start: datetime,
    end: datetime,
    index_prefix: str = "neoneksprod",
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> dict | None:
    """Fetch log context around instances of an error phrase.

    Returns a dict with primary and validation context windows,
    or None if no matching entries are found.
    """
    index = index_names(index_prefix, start, end)

    entries = _find_error_entries(index, container, error_phrase, start, end, count=2)
    if not entries:
        logger.info("No log entries found for phrase '%s' in %s", error_phrase, container)
        return None

    # Primary instance
    primary_entry = entries[0]
    primary_ctx = _fetch_surrounding(index, container, primary_entry["timestamp"], context_lines)

    result = {
        "error_phrase": error_phrase,
        "container": container,
        "primary": {
            "timestamp": primary_entry["timestamp"],
            "error_line": primary_entry["message"],
            "context": primary_ctx["context_text"],
        },
        "validation": None,
    }

    # Validation instance (second entry, if available)
    if len(entries) > 1:
        val_entry = entries[1]
        val_ctx = _fetch_surrounding(index, container, val_entry["timestamp"], context_lines)
        result["validation"] = {
            "timestamp": val_entry["timestamp"],
            "error_line": val_entry["message"],
            "context": val_ctx["context_text"],
        }

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch log context around an error phrase from Elasticsearch"
    )
    parser.add_argument("--container", required=True,
                        help="kubernetes.container.name to query")
    parser.add_argument("--error-phrase", required=True,
                        help="Error phrase to search for in log messages")
    parser.add_argument("--start", required=True,
                        help="Start datetime, e.g. '2026-04-07T00:00:00'")
    parser.add_argument("--end", required=True,
                        help="End datetime, e.g. '2026-04-07T23:59:59'")
    parser.add_argument("--index-prefix", default="neoneksprod",
                        help="ES index prefix (default: neoneksprod)")
    parser.add_argument("--context-lines", type=int, default=DEFAULT_CONTEXT_LINES,
                        help=f"Number of log lines before/after the error (default: {DEFAULT_CONTEXT_LINES})")
    parser.add_argument("--kibana-url", default=None,
                        help="Kibana URL to proxy ES queries through (instead of direct ES)")
    parser.add_argument("--kibana-username", default=None, help="Kibana username for basic auth")
    parser.add_argument("--kibana-password", default=None, help="Kibana password for basic auth")

    args = parser.parse_args()

    init_client(kibana_url=args.kibana_url, kibana_username=args.kibana_username,
                kibana_password=args.kibana_password)

    result = fetch_log_context(
        container=args.container,
        error_phrase=args.error_phrase,
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        index_prefix=args.index_prefix,
        context_lines=args.context_lines,
    )

    if result is None:
        print("No matching log entries found.")
    else:
        print(f"Primary instance ({result['primary']['timestamp']}):")
        print(result["primary"]["context"])
        if result["validation"]:
            print(f"\nValidation instance ({result['validation']['timestamp']}):")
            print(result["validation"]["context"])
        else:
            print("\nOnly one instance found, no validation available.")
