# spec-library

A service specification registry. It discovers `.oncall/oncall.yaml` files from repositories across the GitHub org, caches them in memory, and serves them over a REST API.

Currently the spec contains monitoring and oncall metadata — Datadog service name, Kibana log config, VictoriaMetrics config, oncall channel, and owner team. Other tools in this repo (e.g. `oncall-triage`) can query spec-library at runtime to look up where a service's logs and metrics live.

## Spec Format

Each repo that wants to be discoverable adds a `.oncall/oncall.yaml` at its root:

```yaml
service:
  datadog_name: payment-api
  github_repo: payment-api
  kibana:
    base_url: https://kibana.example.com
    index_pattern: payment-api-*
    default_query: "service.name:payment-api"
  victoria_metrics:
    base_url: https://vm.example.com
    default_query: "up{service=\"payment-api\"}"
  oncall_channel: "#payments-oncall"
  owner_team: payments
```

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/service/{name}` | Get the spec for a service by its `datadog_name` |
| `POST` | `/refresh` | Rescan all org repos and reload specs |
| `POST` | `/refresh` with `{"repo": "repo-name"}` | Reload spec for a single repo (e.g. called from a deploy pipeline) |

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | yes | GitHub personal access token with repo read access |
| `GITHUB_ORG` | yes | GitHub organization to scan |
| `PORT` | no | Server port (default: `8080`) |

## Running Locally

```bash
cd spec-library/src

# install dependencies
go mod download

# set required env vars
export GITHUB_TOKEN="ghp_your-token"
export GITHUB_ORG="your-org"

# run the server
go run main.go
```

The server starts on `http://localhost:8080`.

## Testing Locally

```bash
# 1. Start the server (in one terminal)
cd spec-library/src
GITHUB_TOKEN="ghp_..." GITHUB_ORG="your-org" go run main.go

# 2. Trigger a full rescan to populate the registry
curl -s -X POST http://localhost:8080/refresh | jq .

# 3. Refresh a single repo
curl -s -X POST http://localhost:8080/refresh \
  -d '{"repo": "payment-api"}' | jq .

# 4. Query a service spec
curl -s http://localhost:8080/service/payment-api | jq .

# 5. Verify 404 for unknown service
curl -s -w "\nHTTP %{http_code}\n" http://localhost:8080/service/nonexistent
```
