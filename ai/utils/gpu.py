"""
Device selection for LightGBM.

Despite the filename, this picks the fastest device for our data scale, which is
the CPU. The GPU (OpenCL) path is kept and still works, but only when forced with
ALGOTRADE_LGBM_DEVICE=gpu - at tens of thousands of rows the GPU's kernel-compile
and transfer overhead costs more than it saves, so CPU is the default. LightGBM's
GPU build uses OpenCL (not CUDA) and is often absent from the pip wheel, so when
forced, a tiny probe fit verifies it and falls back to the CPU on failure. The
result is cached so the probe runs at most once per process. Kept named gpu.py to
avoid touching imports across the pipeline.
"""

from __future__ import annotations

import os

import numpy as np

# Cache so the GPU probe runs only once per process.
_RESOLVED_DEVICE: str | None = None


def check_gpu() -> tuple[bool, str]:
    """
    Report whether a CUDA GPU is visible. This is informational only. The training
    code does not rely on it, because LightGBM uses OpenCL, not CUDA.

    Returns:
        (available, human_readable_info)
    """
    try:
        import torch  # optional, only used for a friendly device name

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return True, f"CUDA GPU visible: {name} ({mem_gb:.1f} GB)"
    except Exception:
        pass
    return False, "No CUDA GPU reported by torch"


def resolve_lgbm_device() -> str:
    """
    Decide which device LightGBM should use. Default is the CPU: at this data
    scale (tens of thousands of rows) the OpenCL kernel-compile and transfer
    overhead of the GPU path costs far more than it saves, so the CPU is the
    faster device in wall-clock time. Set ALGOTRADE_LGBM_DEVICE=gpu to force the
    GPU; a tiny probe fit then verifies it and falls back to the CPU on failure.
    """
    global _RESOLVED_DEVICE
    if _RESOLVED_DEVICE is not None:
        return _RESOLVED_DEVICE

    if os.environ.get("ALGOTRADE_LGBM_DEVICE", "").lower() != "gpu":
        _RESOLVED_DEVICE = "cpu"
        print("[gpu] using CPU (fastest at this data scale; "
              "set ALGOTRADE_LGBM_DEVICE=gpu to force the GPU)")
        return _RESOLVED_DEVICE

    try:
        import lightgbm as lgb

        # Two tiny rows are enough to force LightGBM to touch the device.
        x = np.array([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5], [0.2, 0.8]])
        y = np.array([0.0, 1.0, 0.5, 0.7])
        probe = lgb.LGBMRegressor(
            objective="quantile",
            alpha=0.5,
            n_estimators=1,
            device="gpu",
            verbosity=-1,
        )
        probe.fit(x, y)
        _RESOLVED_DEVICE = "gpu"
        print("[gpu] LightGBM GPU (OpenCL) verified -- training will use the GPU")
    except Exception as exc:
        _RESOLVED_DEVICE = "cpu"
        print(f"[gpu] LightGBM GPU not available -- falling back to CPU ({type(exc).__name__})")

    return _RESOLVED_DEVICE
