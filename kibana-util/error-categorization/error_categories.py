"""
Error category discovery and counting utility for Kibana/Elasticsearch.
Uses any LiteLLM-supported LLM to discover error patterns from raw log messages.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import litellm
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

CACHE_DIR = Path("error_category_cache")
CACHE_DIR.mkdir(exist_ok=True)

MAX_ITERATIONS = 10
WORDS_PER_MESSAGE = 20
TOKEN_BUDGET = 40
CHARS_PER_TOKEN = 4
MAX_MESSAGES = (TOKEN_BUDGET * CHARS_PER_TOKEN) // (WORDS_PER_MESSAGE * 6)  # ~6 chars/word

# LiteLLM picks up API keys from env automatically per provider
# e.g. ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY
MODEL = os.getenv("LLM_MODEL", "qwen-local")

es = Elasticsearch([os.getenv("ES_HOST", "http://localhost:9200")])


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
                    "other_bucket_key": "other"
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
                    {"match_phrase": {"kubernetes.container.name": container}},
                    {"range": {"@timestamp": {
                        "gte": start.isoformat(),
                        "lte": end.isoformat(),
                        "format": "strict_date_optional_time"
                    }}},
                    {"multi_match": {"type": "best_fields", "query": "error", "lenient": True}}
                ],
                "must_not": must_not
            }
        }
    }
    resp = es.search(index=index, body=query)
    print(f"Fetched {len(resp['hits']['hits'])} 'other' messages from ES")
    return [hit["_source"]["message"] for hit in resp["hits"]["hits"]]


def run_category_agg(index: str, container: str, start: datetime, end: datetime,
                      categories: dict) -> dict:
    query = build_filter_agg(categories)
    query["query"] = {
        "bool": {
            "filter": [
                {"match_phrase": {"kubernetes.container.name": container}},
                {"range": {"@timestamp": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                    "format": "strict_date_optional_time"
                }}},
                {"multi_match": {"type": "best_fields", "query": "error", "lenient": True}}
            ]
        }
    }
    resp = es.search(index=index, body=query)
    return resp["aggregations"]["error_breakdown"]["buckets"]


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def detect_prefix_pattern(sample_messages: list[str]) -> str:
    samples = "\n".join(sample_messages[:10])
    prompt = f"""These are raw log messages from a Java application:

{samples}

Identify the leading prefix pattern to strip before extracting error content.
The prefix typically includes: timestamp, log level, thread id, logger class name.
Return ONLY a Python regex pattern string (no explanation, no code block) that matches this prefix.
Example: r'\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d+ \\w+ \\d+ --- \\[.*?\\] \\S+ +: '"""

    resp = litellm.completion(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content.strip().strip("r'\"")


def strip_prefix_and_truncate(messages: list[str], prefix_pattern: str) -> list[str]:
    truncated = []
    for msg in messages:
        stripped = re.sub(prefix_pattern, "", msg, count=1).strip()
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
    prompt = f"""You are analyzing error log messages from a backend service.
{existing_text}
New messages to categorize (first {WORDS_PER_MESSAGE} words each):
{messages_text}

Group these into error categories. For each category:
- Use a snake_case label
- Pick a short distinctive phrase from the messages to match it (for use in Elasticsearch match_phrase)
- Do NOT reuse existing category labels unless the message clearly belongs there

Return ONLY valid JSON in this exact format, no explanation:
{{
  "category_label": ["matching phrase"],
  "another_category": ["its matching phrase"]
}}"""

    print("PROMPT :: ", prompt)

    resp = litellm.completion(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.choices[0].message.content.strip()
    # strip markdown code fences if present
    text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


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
        buckets = run_category_agg(index, container_name, start, end, categories)
        other_count = buckets.get("other", {}).get("doc_count", 0)
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
    buckets = run_category_agg(index, container_name, start, end, categories)
    result = {name: data["doc_count"] for name, data in buckets.items()}
    return result


if __name__ == "__main__":
    result = get_error_categories(
        start=datetime(2026, 3, 31, 9, 58, 12),
        end=datetime(2026, 3, 31, 10, 58, 12),
        index_prefix="neoneksprod",
        container_name="bloom"
    )
    print("\nError category counts:")
    for category, count in sorted(result.items(), key=lambda x: -x[1]):
        print(f"  {category}: {count}")
