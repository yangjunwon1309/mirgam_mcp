#!/usr/bin/env bash
# Build CUDA llama.cpp for Jetson Orin (SM 8.7) and fetch Gemma 4 E2B Q4.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_root="$repo_root/.local"
llama_dir="$runtime_root/llama.cpp"
model_dir="$runtime_root/models/gemma-4-e2b"
cuda_compiler="${CMAKE_CUDA_COMPILER:-/usr/local/cuda-12.6/bin/nvcc}"
model_url="https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_0.gguf"
model_path="$model_dir/gemma-4-E2B-it-Q4_0.gguf"

for command in git cmake curl; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
[[ -x "$cuda_compiler" ]] || { echo "CUDA compiler not found: $cuda_compiler" >&2; exit 1; }

mkdir -p "$runtime_root" "$model_dir"
if [[ ! -d "$llama_dir/.git" ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$llama_dir"
fi

cmake -S "$llama_dir" -B "$llama_dir/build" \
  -DGGML_CUDA=ON \
  -DGGML_CUDA_FA=OFF \
  -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
  -DCMAKE_CUDA_ARCHITECTURES=87 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$llama_dir/build" --config Release --target llama-server -j "${BUILD_JOBS:-2}"

curl --fail --location --continue-at - --output "$model_path" "$model_url"
echo "Installed Gemma 4 E2B Q4 at $model_path"
