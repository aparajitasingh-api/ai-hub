# Oncall Triage Agent - Setup Guide

Complete these steps before running the agent for the first time.

---

## 1. Python Environment

```bash
cd oncall-triage

# Create and activate a virtual environment (Python 3.12+)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# (Optional) Install dev dependencies for testing
pip install -e ".[dev]"
```

---

## 2. Datadog Setup

### 2a. Create API & Application Keys

1. Go to **Datadog > Organization Settings > API Keys**
   (`https://app.datadoghq.com/organization-settings/api-keys`)
2. Click **New Key**, name it `oncall-triage-agent`, copy the key
3. Go to **Application Keys** tab, click **New Key**, name it `oncall-triage-agent`, copy the key
4. Set in your `.env`:
   ```
   DD_API_KEY=<your-api-key>
   DD_APP_KEY=<your-application-key>
   DD_SITE=datadoghq.com
   ```
   Use `datadoghq.eu` for EU, `us3.datadoghq.com` for US3, etc.

### 2b. Configure the Webhook Integration

1. Go to **Datadog > Integrations > Webhooks**
   (`https://app.datadoghq.com/integrations/webhooks`)
2. Click **New Webhook** (or **+ New**)
3. Configure:
   - **Name**: `oncall-triage`
   - **URL**: `https://<your-server-host>/api/v1/webhook/datadog`
     (use ngrok or a tunnel for local dev: `ngrok http 8000`)
   - **Payload** (paste this JSON):
     ```json
     {
       "ALERT_ID": "$ALERT_ID",
       "ALERT_METRIC": "$ALERT_METRIC",
       "ALERT_QUERY": "$ALERT_QUERY",
       "ALERT_TITLE": "$ALERT_TITLE",
       "ALERT_TRANSITION": "$ALERT_TRANSITION",
       "ALERT_SCOPE": "$ALERT_SCOPE",
       "ALERT_STATUS": "$ALERT_STATUS",
       "ALERT_TYPE": "$ALERT_TYPE",
       "HOSTNAME": "$HOSTNAME",
       "TAGS": "$TAGS",
       "DATE": "$DATE",
       "LINK": "$LINK",
       "SNAPSHOT": "$SNAPSHOT",
       "EVENT_MSG": "$EVENT_MSG",
       "ORG_ID": "$ORG_ID",
       "PRIORITY": "$PRIORITY"
     }
     ```
   - **Custom Headers**: leave empty (or add auth if you want)
   - Check **Encode as JSON**
4. Click **Save**

### 2c. Attach the Webhook to Monitors

For each Datadog monitor you want triaged:
1. Open the monitor > **Edit**
2. In **Notify your team**, add `@webhook-oncall-triage`
3. Save the monitor

---

## 3. Elasticsearch / Kibana Setup

### 3a. Get Elasticsearch Credentials

**Option A — API Key (recommended):**
1. In Kibana, go to **Stack Management > API Keys**
2. Click **Create API key**
3. Name: `oncall-triage-reader`
4. Role: grant `read` on your log indices (e.g., `app-logs-*`)
5. Copy the Base64-encoded key
6. Set in `.env`:
   ```
   ES_API_KEY=<base64-encoded-api-key>
   ```

**Option B — Basic Auth:**
```
ES_USERNAME=elastic
ES_PASSWORD=<your-password>
```

### 3b. Configure Index and Kibana URL

```
ES_HOSTS=https://your-es-cluster:9200
ES_INDEX_PATTERN=app-logs-*
ES_KIBANA_BASE_URL=https://your-kibana:5601
```

- `ES_INDEX_PATTERN` should match the index pattern where your service logs are stored.
- The agent queries `@timestamp`, `service.name`, `host.name`, `message`, and `log.level` fields.
  If your field names differ, you'll need to adjust `src/clients/elasticsearch.py`.

---

## 4. Google Chat Webhook Setup

1. Open the Google Chat space where alerts should be posted
2. Click the space name (top) > **Apps & integrations** > **Webhooks**
3. Click **Create webhook**
4. Name: `Oncall Triage Bot`
5. Avatar URL: (optional)
6. Click **Create**
7. Copy the webhook URL
8. Set in `.env`:
   ```
   GCHAT_WEBHOOK_URL=https://chat.googleapis.com/v1/spaces/AAAA.../messages?key=...&token=...
   ```

The agent uses `threadKey` to group the triage report and RCA into the same thread.

---

## 5. GitHub Personal Access Token

1. Go to **GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens**
   (`https://github.com/settings/tokens?type=beta`)
2. Click **Generate new token**
3. Configure:
   - **Token name**: `oncall-triage-agent`
   - **Repository access**: select the repos the agent should search
   - **Permissions**: `Contents: Read-only` (minimum required)
4. Click **Generate token**, copy it
5. Set in `.env`:
   ```
   GITHUB_TOKEN=github_pat_...
   GITHUB_ORG=your-org
   GITHUB_DEFAULT_REPOS=service-a,service-b,shared-libs
   ```

`GITHUB_DEFAULT_REPOS` is a comma-separated list of repo names (within the org) that the RCA agent searches for relevant code.

---

## 6. Create Your `.env` File

```bash
cp .env.example .env
# Edit .env with your actual values
```

---

## 7. Run the Agent

### Local Development

```bash
# From the oncall-triage directory, with .venv activated
python -m src.main
```

The server starts on `http://0.0.0.0:8000`. Endpoints:
- `POST /api/v1/webhook/datadog` — receives Datadog alerts
- `GET  /api/v1/health` — health check

### Local Dev with Tunnel (for Datadog to reach you)

```bash
# In a separate terminal
ngrok http 8000
```

Use the ngrok HTTPS URL as the webhook URL in Datadog.

### Production

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Or use Docker, Kubernetes, etc. The app is a standard ASGI application.

---

## 8. Test the Setup

Send a test webhook to verify the pipeline:

```bash
curl -X POST http://localhost:8000/api/v1/webhook/datadog \
  -H "Content-Type: application/json" \
  -d '{
    "ALERT_ID": "test-001",
    "ALERT_METRIC": "system.cpu.idle",
    "ALERT_QUERY": "avg:system.cpu.idle{*}",
    "ALERT_TITLE": "[Test] CPU idle dropped below threshold",
    "ALERT_TRANSITION": "Triggered",
    "ALERT_SCOPE": "host:web-01",
    "ALERT_STATUS": "Alert",
    "ALERT_TYPE": "metric alert",
    "HOSTNAME": "web-01",
    "TAGS": "service:my-service,env:production",
    "DATE": "1710864000",
    "LINK": "https://app.datadoghq.com/monitors/12345",
    "SNAPSHOT": "",
    "EVENT_MSG": "CPU idle dropped below 10%",
    "ORG_ID": "12345",
    "PRIORITY": "P1"
  }'
```

Expected response: `{"status": "accepted", "alert_id": "test-001", "message": "Triage initiated"}`

Check your Google Chat space for the triage report and RCA.

---

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| 422 from webhook endpoint | Verify the Datadog webhook payload JSON matches the expected field names (all caps with aliases) |
| Metrics fetch fails | Verify `DD_API_KEY` and `DD_APP_KEY` are correct; check `DD_SITE` matches your Datadog region |
| Logs fetch fails | Verify ES connectivity, credentials, and that `ES_INDEX_PATTERN` matches your indices |
| Nothing in Google Chat | Verify `GCHAT_WEBHOOK_URL` is correct and the webhook is active in the space |
| RCA finds no code | Verify `GITHUB_TOKEN` has read access, `GITHUB_ORG` and `GITHUB_DEFAULT_REPOS` are correct |
| Connection timeout | If running locally, ensure ngrok tunnel is active and URL is updated in Datadog |
