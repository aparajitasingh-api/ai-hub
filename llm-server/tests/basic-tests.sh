# Direct llama-server test
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-local",
    "messages": [{"role": "user", "content": "write a python hello world"}]
  }' | jq .

echo "========"

# Via LiteLLM proxy (this is what your dev tools should point to)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer anything" \
  -d '{
    "model": "qwen-local",
    "messages": [{"role": "user", "content": "write a python hello world"}]
  }' | jq .

echo "========"

