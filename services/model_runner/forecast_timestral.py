#!/usr/bin/env python3
"""One-forecast CPU child; process exit returns model memory to the operating system."""

from __future__ import annotations

import json
import sys
import time

import numpy as np
import torch
from timestral import TimestralForecaster


def main() -> None:
    request = json.load(sys.stdin)
    values = np.asarray(request["values"], dtype=np.float32)
    horizon = int(request["horizon"])
    if values.ndim != 1 or len(values) < 16 or not 1 <= horizon <= 48:
        raise ValueError("forecast requires at least 16 regularized samples and a horizon of 1 to 48")

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    started = time.perf_counter()
    forecaster = TimestralForecaster.from_pretrained(
        "mistralai/Timestral-28M",
        cache_dir=request["cache_dir"],
        local_files_only=True,
    )
    forecast = forecaster.forecast(values[None, None, :], prediction_length=horizon)
    output = {
        "median": np.asarray(forecast.median).reshape(-1)[:horizon].astype(float).tolist(),
        "q10": np.asarray(forecast.quantile(0.1)).reshape(-1)[:horizon].astype(float).tolist(),
        "q90": np.asarray(forecast.quantile(0.9)).reshape(-1)[:horizon].astype(float).tolist(),
        "model_load_and_forecast_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    print(json.dumps(output, separators=(",", ":")))


if __name__ == "__main__":
    main()
