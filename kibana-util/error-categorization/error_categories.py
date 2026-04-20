"""
Error category discovery and counting utility for Kibana/Elasticsearch.
Uses any LiteLLM-supported LLM to discover error patterns from raw log messages.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import litellm
from dotenv import load_dotenv
from elasticsearch import ElasticsearchException

from kibana_client import KibanaSearchClient, KibanaSearchException, create_search_client

load_dotenv()

logger = logging.getLogger(__name__)

CACHE_DIR = Path("error_category_cache")
CACHE_DIR.mkdir(exist_ok=True)

UNCATEGORIZED_BUCKET = "other"
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 5  # seconds
FALLBACK_PREFIX_PATTERN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ \w+ \d+ --- \[.*?\] \S+ +: "
MAX_ITERATIONS = 10
WORDS_PER_MESSAGE = 10
TOKEN_BUDGET = 500  # tokens reserved for messages within LLM context window
CHARS_PER_TOKEN = 4
AVG_CHARS_PER_WORD = 6
MAX_MESSAGES = (TOKEN_BUDGET * CHARS_PER_TOKEN) // (WORDS_PER_MESSAGE * AVG_CHARS_PER_WORD)  # ~22

# LiteLLM picks up API keys from env automatically per provider
# e.g. ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY
MODEL = os.getenv("LLM_MODEL", "qwen-local")

es = None  # initialized in main or by init_client()


def init_client(kibana_url: str = None, kibana_username: str = None, kibana_password: str = None):
    """Initialize the module-level ES client."""
    global es
    es = create_search_client(kibana_url=kibana_url, kibana_username=kibana_username,
                              kibana_password=kibana_password)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def cache_path(container_name: str) -> Path:
    safe = container_name.replace("/", "_")
    return CACHE_DIR / f"{safe}.json"


def load_cache(container_name: str) -> Optional[dict]:
    p = cache_path(container_name)
    if p.exists():
        return json.loads(p.read_text())
    return None


def save_cache(container_name: str, categories: dict):
    data = {
        "categories": categories,
        "last_updated": datetime.utcnow().isoformat() + "Z"
    }
    cache_path(container_name).write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Index name computation
# ---------------------------------------------------------------------------

def index_names(prefix: str, start: datetime, end: datetime) -> str:
    indices = []
    current = start.date()
    while current <= end.date():
        indices.append(f"{prefix}-{current.strftime('%Y.%m.%d')}")
        current += timedelta(days=1)
    return ",".join(indices)


# ---------------------------------------------------------------------------
# ES helpers
# ---------------------------------------------------------------------------

def build_filter_agg(categories: dict) -> dict:
    filters = {
        name: {"match_phrase": {"message": phrases[0]}}
        for name, phrases in categories.items()
    }
    return {
        "size": 0,
        "aggs": {
            "error_breakdown": {
                "filters": {
                    "filters": filters,
                    "other_bucket_key": UNCATEGORIZED_BUCKET
                }
            }
        }
    }


def fetch_other_messages(index: str, container: str, start: datetime, end: datetime,
                          categories: dict, size: int = MAX_MESSAGES) -> list[str]:
    must_not = [
        {"match_phrase": {"message": phrases[0]}}
        for phrases in categories.values()
    ]
    query = {
        "size": size,
        "_source": ["message"],
        "query": {
            "bool": {
                "filter": [
                    {"term": {"kubernetes.container.name.keyword": container}},
                    {"range": {"@timestamp": {
                        "gte": start.isoformat(),
                        "lte": end.isoformat(),
                        "format": "strict_date_optional_time"
                    }}},
                    {"bool": {
                        "should": [
                            {"match_phrase": {"message": "ERROR"}},
                            {"match_phrase": {"message": "Exception"}},
                            {"match_phrase": {"message": "FATAL"}},
                            {"match_phrase": {"message": "error"}},
                        ],
                        "minimum_should_match": 1
                    }}
                ],
                "must_not": must_not
            }
        }
    }
    try:
        resp = es.search(index=index, body=query)
    except (ElasticsearchException, KibanaSearchException) as e:
        logger.error("ES query failed while fetching uncategorized messages: %s", e)
        return []
    print(f"Fetched {len(resp['hits']['hits'])} 'other' messages from ES")
    return [hit["_source"]["message"] for hit in resp["hits"]["hits"]]


def run_category_agg(index: str, container: str, start: datetime, end: datetime,
                      categories: dict) -> dict:
    query = build_filter_agg(categories)
    query["query"] = {
        "bool": {
            "filter": [
                {"term": {"kubernetes.container.name.keyword": container}},
                {"range": {"@timestamp": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                    "format": "strict_date_optional_time"
                }}},
                {"bool": {
                    "should": [
                        {"match_phrase": {"message": "ERROR"}},
                        {"match_phrase": {"message": "Exception"}},
                        {"match_phrase": {"message": "FATAL"}},
                        {"match_phrase": {"message": "error"}},
                    ],
                    "minimum_should_match": 1
                }}
            ]
        }
    }
    try:
        resp = es.search(index=index, body=query)
    except (ElasticsearchException, KibanaSearchException) as e:
        logger.error("ES aggregation query failed: %s", e)
        return {}
    try:
        return resp["aggregations"]["error_breakdown"]["buckets"]
    except KeyError:
        logger.error("Unexpected aggregation response — check that the index prefix and container are correct. Response: %s", resp)
        return {}


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def detect_prefix_pattern(sample_messages: list[str]) -> str:
    # Truncate each sample to first 200 chars to avoid blowing the context window
    samples = "\n".join(m[:200] for m in sample_messages[:3])
    prompt = f"""These are log messages:

{samples}

Return ONLY a Python regex that matches the prefix (timestamp, log level, thread, class name, colon).
No explanation. Example: \\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d+ \\w+ \\d+ --- \\[.*?\\] \\S+ +: """

    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = litellm.completion(
                model=MODEL,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown backticks, r-prefix, quotes the LLM may wrap around the regex
            raw = re.sub(r"^```[a-z]*|```$", "", raw, flags=re.MULTILINE).strip()
            raw = raw.strip("r'\"` ")
            # Validate the regex before returning
            try:
                re.compile(raw)
            except re.error:
                logger.warning("LLM returned invalid regex: %s — using fallback", raw)
                return FALLBACK_PREFIX_PATTERN
            return raw
        except Exception as e:
            logger.warning("LLM prefix detection attempt %d/%d failed: %s", attempt + 1, LLM_MAX_RETRIES, e)
            if attempt < LLM_MAX_RETRIES - 1:
                time.sleep(LLM_RETRY_DELAY)
    logger.error("LLM prefix detection failed after %d retries — using fallback", LLM_MAX_RETRIES)
    return FALLBACK_PREFIX_PATTERN


def strip_prefix_and_truncate(messages: list[str], prefix_pattern: str) -> list[str]:
    truncated = []
    for msg in messages:
        try:
            stripped = re.sub(prefix_pattern, "", msg, count=1).strip()
        except re.error:
            stripped = msg.strip()
        words = stripped.split()[:WORDS_PER_MESSAGE]
        truncated.append(" ".join(words))
    return truncated


def discover_categories_from_messages(truncated_messages: list[str],
                                       existing_categories: dict) -> dict:
    existing_labels = list(existing_categories.keys()) if existing_categories else []
    messages_text = "\n".join(f"- {m}" for m in truncated_messages)
    existing_text = (
        f"Existing categories: {json.dumps(existing_labels)}\n"
        if existing_labels else ""
    )
    prompt = f"""Group these log messages by error type. Return JSON only.
{existing_text}
{messages_text}

Rules:
- Keys: snake_case names describing the specific error (NEVER use "error", "other", or "unknown" as a key)
- Values: array with EXACTLY ONE phrase, max 5 words, copied from the messages. Do NOT copy the full message.
{f"- Skip existing: {json.dumps(existing_labels)}" if existing_labels else ""}
Example: {{"failed_merge_pdf": ["Failed to merge PDFs"], "no_health_trends": ["No health trends data"]}}"""

    # print("PROMPT :: ", prompt)

    blocked_names = {"error", "other", "category_label", "another_category", "unknown"}

    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = litellm.completion(
                model=MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.choices[0].message.content.strip()
            # strip markdown code fences if present
            text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
            raw = json.loads(text)
            # Sanitize: keep first phrase only, drop generic names, deduplicate by phrase
            sanitized = {}
            seen_phrases = set()
            for k, v in raw.items():
                if k.lower() in blocked_names:
                    logger.warning("Dropping generic category name from LLM output: %s", k)
                    continue
                phrase = v[0] if isinstance(v, list) and v else v if isinstance(v, str) else None
                if not phrase:
                    continue
                if phrase.lower() in seen_phrases:
                    logger.warning("Dropping duplicate phrase for category '%s': %s", k, phrase)
                    continue
                seen_phrases.add(phrase.lower())
                sanitized[k] = [phrase]
            return sanitized
        except json.JSONDecodeError as e:
            logger.warning("LLM returned invalid JSON (attempt %d/%d): %s", attempt + 1, LLM_MAX_RETRIES, e)
        except Exception as e:
            logger.warning("LLM category discovery attempt %d/%d failed: %s", attempt + 1, LLM_MAX_RETRIES, e)
        if attempt < LLM_MAX_RETRIES - 1:
            time.sleep(LLM_RETRY_DELAY)

    logger.error("LLM category discovery failed after %d retries", LLM_MAX_RETRIES)
    return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def get_error_categories(
    start: datetime,
    end: datetime,
    index_prefix: str,
    container_name: str
) -> dict:
    index = index_names(index_prefix, start, end)
    print(f"Using indices: {index}")

    cache = load_cache(container_name)

    if cache is None:
        print("No cache found. Running initial pattern discovery...")
        raw_messages = fetch_other_messages(index, container_name, start, end, {})
        if not raw_messages:
            print("No error messages found.")
            return {}
        prefix_pattern = detect_prefix_pattern(raw_messages)
        print(f"Detected prefix pattern: {prefix_pattern}")
        truncated = strip_prefix_and_truncate(raw_messages, prefix_pattern)
        categories = discover_categories_from_messages(truncated, {})
        save_cache(container_name, categories)
        print(f"Discovered {len(categories)} categories. Cache saved.")
    else:
        categories = cache["categories"]
        print(f"Loaded {len(categories)} categories from cache (last updated: {cache['last_updated']})")

    # Iterative refinement
    for iteration in range(MAX_ITERATIONS):
        if categories:
            buckets = run_category_agg(index, container_name, start, end, categories)
            other_count = buckets.get(UNCATEGORIZED_BUCKET, {}).get("doc_count", 0)
        else:
            other_count = -1  # force fetch when no categories exist yet
        print(f"Iteration {iteration + 1}: other bucket count = {other_count}")

        if other_count == 0:
            break

        print("Fetching 'other' messages for further discovery...")
        raw_messages = fetch_other_messages(index, container_name, start, end, categories)
        if not raw_messages:
            break

        prefix_pattern = detect_prefix_pattern(raw_messages)
        truncated = strip_prefix_and_truncate(raw_messages, prefix_pattern)
        new_categories = discover_categories_from_messages(truncated, categories)

        added = {k: v for k, v in new_categories.items() if k not in categories}
        if not added:
            print("LLM found no new categories. Stopping.")
            break

        print(f"Adding {len(added)} new categories: {list(added.keys())}")
        categories.update(added)
        save_cache(container_name, categories)
    else:
        print(f"Reached max iterations ({MAX_ITERATIONS}). Some messages may remain in 'other'.")

    # Final aggregation
    if not categories:
        print("No categories discovered.")
        return {}
    buckets = run_category_agg(index, container_name, start, end, categories)
    result = {name: data["doc_count"] for name, data in buckets.items()}
    return result


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Discover and count error categories from Kibana logs")
    parser.add_argument("--container", help="kubernetes.container.name to analyse")
    parser.add_argument("--start", help="Start datetime, e.g. '2026-04-02T18:00:00'")
    parser.add_argument("--end", help="End datetime, e.g. '2026-04-02T23:59:59'")
    parser.add_argument("--index-prefix", default="neoneksprod", help="ES index prefix (default: neoneksprod)")
    parser.add_argument("--kibana-url", default=None,
                        help="Kibana URL to proxy ES queries through (instead of direct ES)")
    parser.add_argument("--kibana-username", default=None, help="Kibana username for basic auth")
    parser.add_argument("--kibana-password", default=None, help="Kibana password for basic auth")
    parser.add_argument("--discover-indices", action="store_true",
                        help="List available indices from the cluster and exit")
    args = parser.parse_args()

    init_client(kibana_url=args.kibana_url, kibana_username=args.kibana_username,
                kibana_password=args.kibana_password)

    if args.discover_indices:
        if not isinstance(es, KibanaSearchClient):
            print("--discover-indices requires --kibana-url")
            sys.exit(1)
        print("Saved index patterns in Kibana:")
        for pat in es.list_index_patterns():
            print(f"  {pat['title']}")
        print("\nResolving concrete indices (may be slow)...")
        for idx in es.resolve_indices():
            print(f"  {idx}")
        sys.exit(0)

    if not args.container or not args.start or not args.end:
        parser.error("--container, --start, and --end are required (unless using --discover-indices)")

    result = get_error_categories(
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        index_prefix=args.index_prefix,
        container_name=args.container,
    )
    print("\nError category counts:")
    for category, count in sorted(result.items(), key=lambda x: -x[1]):
        print(f"  {category}: {count}")
