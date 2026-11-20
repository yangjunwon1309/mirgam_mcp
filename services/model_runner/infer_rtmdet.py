#!/usr/bin/env python3
"""One-image TensorRT inference child; process exit releases all CUDA allocations."""

from __future__ import annotations

import ctypes
import gc
import json
import os
import sys
from pathlib import Path

import numpy as np
import tensorrt as trt


REPO_ROOT = Path(__file__).resolve().parents[2]
RTMDET_DIR = Path(os.getenv("RTMDET_MODEL_DIR", REPO_ROOT / ".local/models/rtmdet-tiny"))
sys.path.insert(0, str(RTMDET_DIR))
from infer_engine import COCO_CLASSES, Cuda, OutputAllocator, check_cuda, prepare_image  # noqa: E402


def _class_names() -> list[str]:
    raw_path = os.getenv("RTMDET_CLASS_NAMES_FILE", "")
    if not raw_path:
        return COCO_CLASSES
    value = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    names = value.get("classes", value) if isinstance(value, dict) else value
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("RTMDET_CLASS_NAMES_FILE must contain a JSON string list or {\"classes\": [...]} object")
    return names


def infer(payload: dict[str, object]) -> dict[str, object]:
    image_path = Path(str(payload["image_path"])).resolve()
    threshold = float(payload.get("confidence_threshold", 0.30))
    max_detections = max(1, min(int(payload.get("max_detections", 100)), 300))
    requested_classes = payload.get("classes")
    class_filter = {str(value).casefold() for value in requested_classes} if isinstance(requested_classes, list) else None
    if not 0.01 <= threshold <= 0.99:
        raise ValueError("confidence_threshold must be between 0.01 and 0.99")
    if not image_path.is_file():
        raise FileNotFoundError("camera image file is unavailable")

    class_names = _class_names()
    if requested_classes is not None and not isinstance(requested_classes, list):
        raise ValueError("classes must be a list of supported class names")
    unknown_classes = sorted(
        {str(value).casefold() for value in requested_classes or []}
        - {value.casefold() for value in class_names}
    )
    if unknown_classes:
        return {
            "ok": False,
            "error": "unsupported_classes",
            "label_set": "custom" if os.getenv("RTMDET_CLASS_NAMES_FILE") else "COCO-80",
            "unsupported_classes": unknown_classes,
            "available_classes": class_names,
        }
    engine_path = Path(os.getenv(
        "RTMDET_ENGINE_PATH",
        RTMDET_DIR / "rtmdet-tiny-coco-fp16-ws64.engine",
    ))
    if not engine_path.is_file():
        raise FileNotFoundError("TensorRT engine file is unavailable")

    cuda = Cuda()
    runtime = None
    engine = None
    context = None
    stream = None
    allocators: dict[str, OutputAllocator] = {}
    device_input: int | None = None
    try:
        image, tensor, ratio = prepare_image(image_path)
        runtime = trt.Runtime(trt.Logger(trt.Logger.ERROR))
        engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if engine is None:
            raise RuntimeError("TensorRT failed to deserialize the configured engine")
        context = engine.create_execution_context()
        if context is None:
            raise RuntimeError("TensorRT failed to create an execution context")

        input_name = next(
            engine.get_tensor_name(i) for i in range(engine.num_io_tensors)
            if engine.get_tensor_mode(engine.get_tensor_name(i)) == trt.TensorIOMode.INPUT
        )
        output_names = [
            engine.get_tensor_name(i) for i in range(engine.num_io_tensors)
            if engine.get_tensor_mode(engine.get_tensor_name(i)) == trt.TensorIOMode.OUTPUT
        ]
        device_input = cuda.malloc(3 * 640 * 640 * np.dtype(np.float32).itemsize)
        stream = cuda.new_stream()
        for name in output_names:
            allocator = OutputAllocator(cuda)
            allocators[name] = allocator
            if not context.set_output_allocator(name, allocator):
                raise RuntimeError(f"TensorRT could not set output allocator for {name}")
        context.set_tensor_address(input_name, device_input)
        cuda.copy_to_device(device_input, tensor)
        if not context.execute_async_v3(stream):
            raise RuntimeError("TensorRT inference failed")
        check_cuda(cuda.lib.cudaStreamSynchronize(ctypes.c_void_p(stream)), "cudaStreamSynchronize")

        outputs: dict[str, np.ndarray] = {}
        for name in output_names:
            allocator = allocators[name]
            shape = allocator.shape or tuple(int(value) for value in context.get_tensor_shape(name))
            if any(dim < 0 for dim in shape):
                raise RuntimeError(f"TensorRT returned unresolved output shape for {name}")
            dtype = np.float32 if name == "dets" else np.int64
            count = int(np.prod(shape))
            raw = cuda.copy_to_host(allocator.ptr, count * np.dtype(dtype).itemsize) if count else b""
            outputs[name] = np.frombuffer(raw, dtype=dtype).copy().reshape(shape)

        detections = []
        for row, label in zip(outputs["dets"].reshape(-1, 5), outputs["labels"].reshape(-1)):
            x1, y1, x2, y2, score = [float(value) for value in row]
            class_id = int(label)
            name = class_names[class_id] if 0 <= class_id < len(class_names) else f"class_{class_id}"
            if score < threshold or (class_filter is not None and name.casefold() not in class_filter):
                continue
            width, height = image.shape[1], image.shape[0]
            box = [
                round(min(width, max(0.0, x1 / ratio)), 1),
                round(min(height, max(0.0, y1 / ratio)), 1),
                round(min(width, max(0.0, x2 / ratio)), 1),
                round(min(height, max(0.0, y2 / ratio)), 1),
            ]
            detections.append({"class_id": class_id, "class": name, "score": round(score, 4), "bbox_xyxy": box})
        detections.sort(key=lambda item: float(item["score"]), reverse=True)
        counts: dict[str, int] = {}
        for item in detections:
            name = str(item["class"])
            counts[name] = counts.get(name, 0) + 1
        detections_total = len(detections)
        return {
            "ok": True,
            "model": engine_path.name,
            "label_set": "custom" if os.getenv("RTMDET_CLASS_NAMES_FILE") else "COCO-80",
            "image_size": {"width": int(image.shape[1]), "height": int(image.shape[0])},
            "confidence_threshold": threshold,
            "counts_by_class": counts,
            "detections_total": detections_total,
            "detections_returned": min(detections_total, max_detections),
            "detections_truncated": detections_total > max_detections,
            "detections": detections[:max_detections],
            "unsupported_classes": [],
        }
    finally:
        if stream:
            try:
                check_cuda(cuda.lib.cudaStreamSynchronize(ctypes.c_void_p(stream)), "cudaStreamSynchronize")
            except Exception:
                pass
        for allocator in allocators.values():
            cuda.free(allocator.ptr)
        cuda.free(device_input)
        if stream:
            cuda.lib.cudaStreamDestroy(ctypes.c_void_p(stream))
        del context, engine, runtime
        gc.collect()


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(infer(request), ensure_ascii=False, separators=(",", ":")))
