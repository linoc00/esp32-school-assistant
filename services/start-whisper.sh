#!/bin/sh
set -eu

WHISPER_CPP_DIR="${WHISPER_CPP_DIR:-$HOME/whisper.cpp}"
WHISPER_BINARY="$WHISPER_CPP_DIR/build/bin/whisper-server"
WHISPER_MODEL="${WHISPER_MODEL:-$WHISPER_CPP_DIR/models/ggml-base.bin}"

if [ ! -x "$WHISPER_BINARY" ]; then
  echo "whisper-server non trovato in: $WHISPER_BINARY" >&2
  echo "Compilalo con: cmake --build $WHISPER_CPP_DIR/build --target whisper-server" >&2
  exit 1
fi

if [ ! -f "$WHISPER_MODEL" ]; then
  echo "Modello Whisper non trovato in: $WHISPER_MODEL" >&2
  exit 1
fi

exec "$WHISPER_BINARY" \
  --model "$WHISPER_MODEL" \
  --language it \
  --host 127.0.0.1 \
  --port 8081 \
  --no-gpu \
  --convert \
  --no-timestamps \
  --suppress-nst
