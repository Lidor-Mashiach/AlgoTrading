"""
Thin logging shim for the AI side.

Every AI script prints lines shaped like "[stage] message" (e.g. "[extract] done").
This wraps the backend ConsoleLogger so those lines get the same colors and level
prefixes, without duplicating the logger - the backend module is pure aesthetics,
so importing it here does not cross any logic boundary.

Usage:
    from utils.log import log
    log("[extract] pooled table ready")          # INFO (cyan), default
    log("[extract] missing columns", "WARNING")  # yellow
    log("[verify] all bands valid", "OK")        # green

Note: the backend ConsoleLogger is loaded by file path, not by "from utils...",
because both ai/ and backend/ have a utils package - a plain import would collide
with ai/utils. Loading by path avoids that ambiguity entirely.
"""

from __future__ import annotations

import importlib.util
import pathlib

# Load backend/utils/ConsoleLogger.py by explicit file path (aesthetics only).
_LOGGER_PATH = pathlib.Path(__file__).resolve().parents[2] / "backend" / "utils" / "ConsoleLogger.py"
_spec = importlib.util.spec_from_file_location("_backend_console_logger", _LOGGER_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
ConsoleLogger = _module.ConsoleLogger

_logger = ConsoleLogger("ai")

_METHODS = {
    "INFO": _logger.info,
    "OK": _logger.success,
    "WARNING": _logger.warning,
    "ERROR": _logger.error,
    "DEBUG": _logger.debug,
}


def log(message: str, level: str = "INFO") -> None:
    """Print one colored, timestamped, level-prefixed line. Default level INFO."""
    _METHODS.get(level, _logger.info)(message)
