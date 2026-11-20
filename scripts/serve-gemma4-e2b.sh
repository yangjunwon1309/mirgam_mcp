#!/usr/bin/env bash
# Start the locally built CUDA llama.cpp server for Gemma 4 E2B Q4 on Jetson Orin 8 GB.
# Requires scripts/install-gemma4-e2b.sh to have completed successfully.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
server="${LLAMA_SERVER:-$repo_root/.local/llama.cpp/build/bin/llama-server}"
model="${GEMMA_MODEL_PATH:-$repo_root/.local/models/gemma-4-e2b/gemma-4-E2B-it-Q4_0.gguf}"

if [[ ! -x "$server" ]]; then
  echo "llama-server is missing: $server" >&2
  echo "Run scripts/install-gemma4-e2b.sh first." >&2
  exit 1
fi

if [[ ! -s "$model" ]]; then
  echo "Gemma model is missing or empty: $model" >&2
  echo "Run scripts/install-gemma4-e2b.sh first." >&2
  exit 1
fi

# On this 8 GB Jetson, CUDA graph instantiation can fail even after the model
# loads successfully. llama.cpp supports disabling CUDA graphs at runtime; keep
# the option opt-in because graphs can improve decode throughput on larger GPUs.
if [[ "${GEMMA_CUDA_GRAPHS:-off}" != "on" ]]; then
  export GGML_CUDA_DISABLE_GRAPHS=1
else
  unset GGML_CUDA_DISABLE_GRAPHS || true
fi

exec "$server" \
  --model "$model" \
  --alias gemma-4-e2b \
  --host "${GEMMA_HOST:-0.0.0.0}" \
  --port "${GEMMA_PORT:-8000}" \
  --ctx-size "${GEMMA_CONTEXT_SIZE:-1024}" \
  --batch-size "${GEMMA_BATCH_SIZE:-16}" \
  --ubatch-size "${GEMMA_UBATCH_SIZE:-8}" \
  --parallel 1 \
  --n-gpu-layers "${GEMMA_GPU_LAYERS:-99}" \
  --flash-attn off \
  --jinja
