# LLM Server — Self-Hosted Setup

Internal LLM inference server for developer automation tooling. Provides an OpenAI-compatible API backed by a self-hosted Qwen2.5-Coder model, managed via LiteLLM Proxy. Designed to replace per-developer Claude/Gemini API keys with a shared, cost-controlled inference endpoint for programmatic access using curated prompts.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Expected Usage Pattern](#expected-usage-pattern)
- [Cost Comparison](#cost-comparison)
- [Model Configuration](#model-configuration)
- [Local Development Setup (Docker)](#local-development-setup-docker)
- [Kubernetes Deployment (EKS)](#kubernetes-deployment-eks)
- [Scale-from-Zero (KEDA)](#scale-from-zero-keda)
- [Monitoring](#monitoring)

---

## Architecture Overview

```
dev tools / automation scripts
            |
            v
  KEDA HTTP Interceptor          <- queues requests when pods are at 0
            |
            v
     LiteLLM Proxy :4000         <- auth, rate limiting, usage logging, routing
            |
            v
     llama-server :8080          <- inference server (llama.cpp)
            |
            v
  Qwen2.5-Coder GGUF model       <- loaded from EFS PVC
```

### Components

**llama-server** — llama.cpp's built-in HTTP server. Loads a GGUF model file and exposes an OpenAI-compatible `/v1/chat/completions` endpoint. Image: `ghcr.io/ggml-org/llama.cpp:server`.

**LiteLLM Proxy** — Gateway layer. Handles API key issuance per team, rate limiting, usage logging, and backend routing. Devs point their LiteLLM or OpenAI SDK at this proxy. Image: `ghcr.io/berriai/litellm:main-latest`.

**KEDA HTTP Add-on** — Enables scale-from-zero. Intercepts incoming HTTP requests, holds them in a queue while pods scale up from 0, and forwards once the pod is ready. Removes need for manual infra intervention on idle clusters.

**Argo Rollouts** — Manages rolling deployments of llama-server with a manual promotion gate at 50% weight.

**AWS EFS** — Persistent volume for model files. Shared across all llama-server pods via ReadWriteMany PVC. Model is downloaded once on first run via an init container and reused on all subsequent starts.

---

## Expected Usage Pattern

| Parameter | Current | 10x Scale |
|---|---|---|
| Requests/day | 1,000 | 10,000 |
| Requests/month | ~30,000 | ~300,000 |
| Avg input tokens/request | ~2,000 | ~2,000 |
| Avg output tokens/request | ~300 | ~300 |
| Input tokens/month | 60M | 600M |
| Output tokens/month | 9M | 90M |
| Total tokens/month | 69M | 690M |
| Avg context window needed | 4K | 4K |
| Concurrent users (peak est.) | 5–10 | 50–100 |

Prompts are structured, developer-authored, and automation-focused — not conversational. Inputs are medium-to-large with short, bounded outputs. No multi-turn history. This makes lower quantization levels more viable than open-ended use cases.

---

## Cost Comparison

Self-hosted 70B baseline (reserved instance) breaks even vs Bedrock at ~8K–9K req/day. The cost-optimised 70B option is the most cost effective at 10x scale but carries quality risk. The cost crossover points are highly dependent on actual prompt token counts and the quality requirements of the use case.

| Option | Payment model | Instance | Config | Model | 1K req/day realistic | 10K req/day realistic | Model quality | Throttling risk | Idle cost risk | Hidden costs |
|---|---|---|---|---|---|---|---|---|---|---|
| Bedrock (Llama 70B) | Per token | None (managed) | — | Llama 3.3 70B | ~$100–140/mo | ~$820–1,100/mo | High | Yes | No | Retries on throttled requests, CloudWatch ingestion (~$5–15/mo), experimentation burn in first month (2–3x token cost), no per-team visibility without custom tagging |
| Vertex AI (Llama 70B) | Per token | None (managed) | — | Llama 3.3 70B | ~$70–100/mo | ~$550–750/mo | High | Yes | Yes (self-deploy) | Egress fees ($0.12/GB), idle endpoint charges if self-deployed, no guided cost estimator so scaling surprises are common |
| Self-hosted 14B | Per instance-hour | c6i.4xlarge (16 vCPU, 32 GiB) | Q4_K_M, ctx 4096, parallel 4 | Qwen2.5-Coder 14B | ~$320–520/mo | ~$630–1,020/mo | Medium | No | Yes | Eng setup (1–2 weeks), maintenance (~4h/mo), observability via LiteLLM+Datadog, EBS storage (~$2/mo), quality gap may cause fallback to paid APIs |
| Self-hosted 70B (baseline) | Per instance-hour | r6i.2xlarge (8 vCPU, 64 GiB) | Q4_K_M, ctx 4096, parallel 4 | Qwen2.5 72B | ~$390–520/mo | ~$780–1,000/mo | High | No | Yes | Same as 14B. Slow CPU throughput (~2–5 tok/s) may require queue management under load |
| Self-hosted 70B (cost-optimised) | Per instance-hour | r6i.xlarge (4 vCPU, 32 GiB) | Q2_K, ctx 4096, parallel 2 | Qwen2.5 72B | ~$190–250/mo | ~$380–500/mo | Medium-low* | No | Yes | Same as above plus risk of quality-driven fallback to paid APIs if Q2_K proves insufficient. Must validate against actual prompts* |
| Self-hosted 70B (balanced) | Per instance-hour | r6i.2xlarge (8 vCPU, 64 GiB) | Q3_K_M, ctx 4096, parallel 4 + KV cache q8_0 | Qwen2.5 72B | ~$390–520/mo | ~$780–1,000/mo | Medium-high* | No | Yes | Same as baseline. KV cache quantization adds minor implementation complexity but no additional cost |

*Validate against actual scripted prompts before committing. GGUF models: https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF

---

## Model Configuration

Model behaviour is controlled via environment variables. In Kubernetes these are managed via a ConfigMap. In Docker they are passed as env overrides.

| Variable | Default | Description |
|---|---|---|
| `MODEL_FILE` | `qwen2.5-coder-14b-instruct-q4_k_m.gguf` | GGUF model filename in `/models` |
| `HF_MODEL_REPO` | `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF` | HuggingFace repo for init container download |
| `CTX_SIZE` | `4096` | Context window size in tokens |
| `PARALLEL` | `4` | Max concurrent requests |
| `CACHE_TYPE_K` | `q8_0` | KV cache key quantization |
| `CACHE_TYPE_V` | `q8_0` | KV cache value quantization |

### Quantization tradeoffs for 70B model

| Quantization | Model size | Min RAM | Instance | Quality |
|---|---|---|---|---|
| Q4_K_M | ~40GB | 64GB | r6i.2xlarge | High (recommended floor) |
| Q3_K_M + KV q8_0 | ~30GB | 48GB | r6i.xlarge (tight) | Medium-high |
| Q2_K | ~22GB | 32GB | r6i.xlarge | Medium-low (validate first) |

---

## Local Development Setup (Docker) (use ollama whenever possible)

### Prerequisites

- Docker Desktop installed and running
- M-series Mac with 16GB RAM recommended (Intel Macs will be slower)

### Directory structure

```
llm-local/
├── docker-compose.yml
├── litellm/
│   └── config.yaml
└── models/          # GGUF files go here
```

### Download a model

```bash
mkdir -p llm-local/models && cd llm-local/models

# Small model for setup validation (~4GB)
curl -L -o qwen2.5-coder-7b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf

# Full 14B model (~9GB)
curl -L -o qwen2.5-coder-14b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/qwen2.5-coder-14b-instruct-q4_k_m.gguf
```

### docker-compose.yml

```yaml
services:
  llama-server:
    image: ghcr.io/ggml-org/llama.cpp:server
    platform: linux/arm64
    volumes:
      - ./models:/models
    environment:
      LLAMA_ARG_MODEL: /models/${MODEL_FILE:-qwen2.5-coder-7b-instruct-q4_k_m.gguf}
      LLAMA_ARG_CTX_SIZE: ${CTX_SIZE:-4096}
      LLAMA_ARG_N_PARALLEL: ${PARALLEL:-2}
      LLAMA_ARG_HOST: 0.0.0.0
      LLAMA_ARG_PORT: 8080
      LLAMA_ARG_CACHE_TYPE_K: ${CACHE_TYPE_K:-q8_0}
      LLAMA_ARG_CACHE_TYPE_V: ${CACHE_TYPE_V:-q8_0}
      LLAMA_ARG_NO_MMAP: 1
      LLAMA_ARG_ENDPOINT_METRICS: 1
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    volumes:
      - ./litellm/config.yaml:/app/config.yaml
    command: --config /app/config.yaml --port 4000
    ports:
      - "4000:4000"
    depends_on:
      llama-server:
        condition: service_healthy
```

### litellm/config.yaml

```yaml
model_list:
  - model_name: qwen-local
    litellm_params:
      model: openai/qwen-local
      api_base: http://llama-server:8080/v1
      api_key: none
```

### Run

```bash
cd llm-local

# Default: 7B model (safe for 16GB Mac)
docker compose up

# Swap to 14B
MODEL_FILE=qwen2.5-coder-7b-instruct-q4_k_m.gguf docker compose up

# Reduce context if RAM is tight
MODEL_FILE=qwen2.5-coder-7b-instruct-q4_k_m.gguf CTX_SIZE=2048 PARALLEL=1 docker compose up
```

### Test

```bash
# Health check
curl http://localhost:8080/health

# Via LiteLLM proxy (use this endpoint in dev tools)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer anything" \
  -d '{
    "model": "qwen-local",
    "messages": [{"role": "user", "content": "write a python hello world"}]
  }'
```

### RAM expectations on M-series Mac

| Config | RAM usage | Safe on 16GB? |
|---|---|---|
| 7B Q4_K_M, ctx 2048, parallel 1 | ~6–7GB | Yes |
| 7B Q4_K_M, ctx 4096, parallel 2 | ~8–9GB | Yes |
| 14B Q4_K_M, ctx 2048, parallel 1 | ~10–11GB | Yes, tight |
| 14B Q4_K_M, ctx 4096, parallel 2 | ~13–14GB | Borderline |

---

```markdown
## Local Development Setup (macOS — Ollama)

Recommended for Apple Silicon Macs. Ollama runs natively on macOS and uses Metal GPU directly,
giving 10–20x better throughput than Docker-based llama-server on M-series chips.

### Install

```bash
brew install ollama
```

### Shell configuration

Add to `~/.zshrc`:

```bash
export OLLAMA_FLASH_ATTENTION=1   # significant speedup on Apple Silicon
export OLLAMA_KEEP_ALIVE=1h       # keep model loaded between requests
```

Then:

```bash
source ~/.zshrc
```

### Pull models

```bash
# for stack validation (fast, ~60-80 tok/s on M4)
ollama pull qwen2.5-coder:3b

# for quality testing
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
```

### Run

```bash
ollama serve &
ollama run qwen2.5-coder:3b "write a python hello world"
```

Verify GPU is being used:

```bash
ollama ps
# PROCESSOR column should show Metal, not CPU
```

### Connect LiteLLM to Ollama

Update `litellm/config.yaml`:

```yaml
model_list:
  - model_name: qwen-local
    litellm_params:
      model: ollama/qwen2.5-coder:3b
      api_base: http://host.docker.internal:11434
```

Run only LiteLLM in Docker (Ollama runs natively outside Docker):

```bash
docker compose up litellm
```

### Troubleshooting

**Model using CPU instead of Metal** — another process (e.g. Docker Desktop) is consuming
unified memory. Stop Docker Desktop, then unload and reload the model:

```bash
curl http://localhost:11434/api/generate \
  -d '{"model": "qwen2.5-coder:3b", "keep_alive": 0}'
ollama run qwen2.5-coder:3b "hello"
```

**First request is slow** — Metal compiles GPU kernels on first use per session. The second
request onwards will be at full speed.

**Checking actual throughput**:

```bash
ollama run --verbose qwen2.5-coder:3b "write a python function to reverse a string"
# prints eval rate: X tokens/s at the end
```

### RAM expectations on Apple Silicon

| Model | Approx tok/s (M4) | Safe on 16GB with Docker stopped? |
|---|---|---|
| 3B Q4_K_M | ~60–80 | Yes |
| 7B Q4_K_M | ~30–50 | Yes |
| 14B Q4_K_M | ~10–20 | Yes, but close |
```

## Kubernetes Deployment (EKS)

### Prerequisites

- EKS cluster with a dedicated node group for LLM workloads
- AWS EFS CSI driver installed: https://docs.aws.amazon.com/eks/latest/userguide/efs-csi.html
- Argo Rollouts controller installed: https://argoproj.github.io/argo-rollouts/
- `efs-sc` StorageClass configured

### Directory structure

```
k8s/llm-server/
├── namespace.yaml
├── configmap.yaml
├── pvc.yaml
├── rollout.yaml
├── service.yaml
├── keda-http-litellm.yaml
├── keda-http-llama.yaml
├── ingress.yaml
└── litellm/
    ├── configmap.yaml
    ├── deployment.yaml
    └── service.yaml
```

### Apply order

```bash
kubectl apply -f k8s/llm-server/namespace.yaml
kubectl apply -f k8s/llm-server/pvc.yaml
kubectl apply -f k8s/llm-server/configmap.yaml
kubectl apply -f k8s/llm-server/rollout.yaml
kubectl apply -f k8s/llm-server/service.yaml
kubectl apply -f k8s/llm-server/litellm/
kubectl apply -f k8s/llm-server/keda-http-litellm.yaml
kubectl apply -f k8s/llm-server/keda-http-llama.yaml
kubectl apply -f k8s/llm-server/ingress.yaml
```

### Model download

On first pod start, the init container checks if the model file exists on the EFS volume. If not, it downloads it from HuggingFace using `huggingface-cli`. Subsequent pod restarts skip the download. This means first-run on a new EFS volume will take several minutes depending on model size.

### Updating model or config

Edit `k8s/llm-server/configmap.yaml` and reapply:

```bash
kubectl apply -f k8s/llm-server/configmap.yaml
```

Argo Rollouts will detect the pod template change and begin a new rolling update. The rollout pauses at 50% weight for manual promotion. To promote:

```bash
kubectl argo rollouts promote llama-server -n llm-server
```

To remove the manual gate, delete the `pause: {}` step from `rollout.yaml`.

---

## Scale-from-Zero (KEDA)

### Problem

When the node group scales to 0, pods are also at 0 replicas. HPA cannot scale from 0 — it requires at least one running pod to read metrics. Without intervention, the cluster stays at 0 indefinitely.

### Solution

KEDA HTTP Add-on intercepts incoming requests and triggers pod scale-up before forwarding. Requests are queued during cold start.

**Cold start time**: ~4–5 minutes total (node provisioning ~2–3 min + model load from EFS ~1–2 min). Communicate this to devs — the first request after an idle period will be slow.

### Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# KEDA core
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace

# HTTP add-on
helm install http-add-on kedacore/keda-add-ons-http \
  --namespace keda \
  --set interceptor.responseTimeout=300s
```

### Scale pods to 0 (hand off to KEDA)

After KEDA is installed and HTTPScaledObjects are applied, hand off scaling:

```bash
kubectl scale deployment litellm --replicas=0 -n llm-server
kubectl argo rollouts scale llama-server --replicas=0 -n llm-server
```

KEDA owns scaling from this point. Do not manually scale these resources.

### Verify node autoscaler

To confirm which node autoscaler is managing the dedicated node group:

```bash
kubectl get pods -n kube-system | grep -E 'karpenter|cluster-autoscaler'
```

Both Karpenter and Cluster Autoscaler support scale-from-zero and will provision nodes automatically when KEDA creates pending pods. No additional configuration is needed for node scale-up once pod scaling is handled by KEDA.

---

## Monitoring

### llama-server metrics

llama-server exposes Prometheus metrics at `/metrics` when `LLAMA_ARG_ENDPOINT_METRICS=1` is set (already included in the manifests).

Key metrics:

| Metric | Description |
|---|---|
| `llamacpp_prompt_tokens_total` | Total input tokens processed |
| `llamacpp_completion_tokens_total` | Total output tokens generated |
| `llamacpp_requests_processing` | Concurrent requests in flight |
| `llamacpp_requests_deferred` | Queued requests (indicates saturation) |
| `llamacpp_kv_cache_usage_ratio` | KV cache utilisation (high = needs more RAM or lower ctx) |

### LiteLLM usage logging

LiteLLM can emit per-request metadata (input tokens, output tokens, model, team tag) to Datadog as custom metrics. Add to `litellm/config.yaml`:

```yaml
litellm_settings:
  success_callback: ["datadog"]
  failure_callback: ["datadog"]

environment_variables:
  DD_API_KEY: "<your-datadog-api-key>"
```

Reference: https://docs.litellm.ai/docs/proxy/logging#datadog

### Bedrock metrics (if using managed option)

Bedrock publishes to CloudWatch under the `AWS/Bedrock` namespace:

| Metric | Description |
|---|---|
| `InputTokenCount` | Input tokens per request |
| `OutputTokenCount` | Output tokens per request |
| `InvocationThrottles` | Throttled request count — key signal for shared capacity pressure |
| `InvocationLatency` | End-to-end latency |
| `FirstByteLatency` | Time to first token |

Reference: https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-cw.html

---

## References

- llama.cpp Docker images: https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md
- llama-server config reference: https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md
- LiteLLM Proxy quickstart: https://docs.litellm.ai/docs/proxy/quick_start
- Qwen2.5 GGUF models: https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF
- KEDA HTTP add-on: https://github.com/kedacore/http-add-on
- AWS EFS CSI driver: https://docs.aws.amazon.com/eks/latest/userguide/efs-csi.html
- Argo Rollouts: https://argoproj.github.io/argo-rollouts/
- llama.cpp quantization guide: https://github.com/ggerganov/llama.cpp/blob/master/docs/quantization.md
- Bedrock monitoring: https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-cw.html
