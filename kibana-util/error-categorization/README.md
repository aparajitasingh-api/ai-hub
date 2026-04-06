# Error Categorization

Discovers and counts error categories from Kibana/Elasticsearch logs for any kubernetes container using an LLM.

## Usage

```bash
python error_categories.py --container <container_name> --start <start_datetime> --end <end_datetime> [--index-prefix <prefix>]
```

### Example

```bash
python error_categories.py --container club-service --start 2026-04-02T18:00:00 --end 2026-04-02T23:59:59
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--container` | Yes | - | `kubernetes.container.name` to analyse |
| `--start` | Yes | - | Start datetime (ISO format) |
| `--end` | Yes | - | End datetime (ISO format) |
| `--index-prefix` | No | `neoneksprod` | Elasticsearch index prefix |

## Environment Variables

Configure via `.env` file or environment:

- `ES_HOST` - Elasticsearch URL (default: `http://localhost:9200`)
- `LLM_MODEL` - LiteLLM model identifier (default: `qwen-local`)
- `OPENAI_API_BASE` - API base URL for OpenAI-compatible LLM endpoints
- `OPENAI_API_KEY` - API key (if required by provider)
