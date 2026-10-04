#!/bin/sh
set -eu

LLAMA_BINARY="${LLAMA_BINARY:-$HOME/.local/bin/llama}"
LLAMA_MODEL_REPO="${LLAMA_MODEL_REPO:-openbmb/MiniCPM5-2B-GGUF:Q4_K_M}"
LLAMA_API_KEY="${LLAMA_API_KEY:-school-assistant-local-change-me}"

if [ ! -x "$LLAMA_BINARY" ]; then
  echo "Comando llama non trovato in: $LLAMA_BINARY" >&2
  exit 1
fi

exec "$LLAMA_BINARY" serve \
  --hf-repo "$LLAMA_MODEL_REPO" \
  --offline \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size 4096 \
  --parallel 2 \
  --gpu-layers all \
  --reasoning off \
  --reasoning-budget 0 \
  --no-reasoning-preserve \
  --api-key "$LLAMA_API_KEY" \
  --no-webui
