# Error Categorization

Discovers and counts error categories from Kibana/Elasticsearch logs for any kubernetes container using an LLM.

## Usage

### Direct Elasticsearch

```bash
python error_categories.py --container <container_name> --start <start_datetime> --end <end_datetime> [--index-prefix <prefix>]
```

### Via Kibana (when you don't have direct ES access)

```bash
# Discover available indices on the cluster
python error_categories.py --kibana-url <kibana_url> --discover-indices

# Run error categorization through Kibana
python error_categories.py --kibana-url <kibana_url> --container <container_name> --start <start_datetime> --end <end_datetime> [--index-prefix <prefix>]
```

### Examples

```bash
# Direct ES
python error_categories.py --container club-service --start 2026-04-02T18:00:00 --end 2026-04-02T23:59:59

# Via Kibana
python error_categories.py --kibana-url http://kibana.internal:5601 --container club-service --start 2026-04-02T18:00:00 --end 2026-04-02T23:59:59

# Discover indices on a Kibana cluster
python error_categories.py --kibana-url http://kibana.internal:5601 --discover-indices
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--container` | Yes (unless `--discover-indices`) | - | `kubernetes.container.name` to analyse |
| `--start` | Yes (unless `--discover-indices`) | - | Start datetime (ISO format) |
| `--end` | Yes (unless `--discover-indices`) | - | End datetime (ISO format) |
| `--index-prefix` | No | `neoneksprod` | Elasticsearch index prefix |
| `--kibana-url` | No | - | Kibana URL to proxy queries through (instead of direct ES) |
| `--kibana-username` | No | - | Kibana username for basic auth |
| `--kibana-password` | No | - | Kibana password for basic auth |
| `--discover-indices` | No | - | List available indices from Kibana and exit |

### Log Context Fetcher

```bash
# Direct ES
python log_context_fetcher.py --container club-service --error-phrase "Failed to merge PDFs" --start 2026-04-07T00:00:00 --end 2026-04-07T23:59:59

# Via Kibana
python log_context_fetcher.py --kibana-url http://kibana.internal:5601 --container club-service --error-phrase "Failed to merge PDFs" --start 2026-04-07T00:00:00 --end 2026-04-07T23:59:59
```

## Environment Variables

Configure via `.env` file or environment:

- `ES_HOST` - Elasticsearch URL (default: `http://localhost:9200`)
- `KIBANA_URL` - Kibana URL for proxied queries (alternative to `--kibana-url` flag)
- `KIBANA_USERNAME` - Kibana username for basic auth
- `KIBANA_PASSWORD` - Kibana password for basic auth
- `LLM_MODEL` - LiteLLM model identifier (default: `qwen-local`)
- `OPENAI_API_BASE` - API base URL for OpenAI-compatible LLM endpoints
- `OPENAI_API_KEY` - API key (if required by provider)

## Prerequisites

Port-forward LiteLLM for LLM access:

```bash
kubectl port-forward -n ai-hub svc/litellm 4000:4000
```
