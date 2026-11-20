#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="${RTMDET_MODEL_DIR:-${repo_root}/.local/models/rtmdet-tiny}"
trtexec="${TRTEXEC:-/usr/src/tensorrt/bin/trtexec}"
onnx="${RTMDET_ONNX_PATH:-${model_dir}/rtmdet-tiny-coco-topk3840.onnx}"
engine="${RTMDET_ENGINE_PATH:-${model_dir}/rtmdet-tiny-coco-fp16-ws64.engine}"

[[ -x "${trtexec}" ]] || { echo "TensorRT trtexec not found: ${trtexec}" >&2; exit 1; }
[[ -s "${onnx}" ]] || { echo "RTMDet ONNX model not found: ${onnx}" >&2; exit 1; }

exec "${trtexec}" \
  --onnx="${onnx}" \
  --saveEngine="${engine}" \
  --fp16 \
  --memPoolSize=workspace:64 \
  --builderOptimizationLevel=0 \
  --skipInference
