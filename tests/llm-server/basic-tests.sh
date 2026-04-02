#!/usr/bin/env bash
# Integration tests for llm-server (ollama-server + litellm).
# Run after: docker compose up -d  (from this directory)

set -euo pipefail

echo "=== Direct llama-server test ==="
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-local",
    "messages": [{"role": "user", "content": "write a python hello world"}]
  }' | jq .

echo "========"

echo "=== Via LiteLLM proxy ==="
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer anything" \
  -d '{
    "model": "qwen-local",
    "messages": [{"role": "user", "content": "write a python hello world"}]
  }' | jq .

echo "========"
