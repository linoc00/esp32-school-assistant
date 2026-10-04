#!/bin/sh
set -eu

LLAMA_BINARY="${LLAMA_BINARY:-$HOME/.local/bin/llama}"
EMBEDDINGS_MODEL_REPO="${EMBEDDINGS_MODEL_REPO:-Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0}"
EMBEDDINGS_API_KEY="${EMBEDDINGS_API_KEY:-school-assistant-embeddings-local}"

if [ ! -x "$LLAMA_BINARY" ]; then
  echo "Comando llama non trovato in: $LLAMA_BINARY" >&2
  exit 1
fi

exec "$LLAMA_BINARY" serve \
  --hf-repo "$EMBEDDINGS_MODEL_REPO" \
  --offline \
  --embedding \
  --host 127.0.0.1 \
  --port 8082 \
  --ctx-size 2048 \
  --parallel 2 \
  --gpu-layers all \
  --api-key "$EMBEDDINGS_API_KEY" \
  --no-webui
