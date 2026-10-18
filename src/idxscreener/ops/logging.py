"""FR-OPS-06: structured JSON logging with run_id and correlation_id."""
from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any


class _JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str, correlation_id: str) -> None:
        super().__init__()
        self._run_id = run_id
        self._correlation_id = correlation_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "run_id": self._run_id,
            "correlation_id": self._correlation_id,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_run_logger(
    name: str = "idxscreener",
    run_id: str | None = None,
    correlation_id: str | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Return a logger that emits one JSON line per record."""
    run_id = run_id or str(uuid.uuid4())
    correlation_id = correlation_id or run_id
    logger = logging.getLogger(f"{name}.{run_id[:8]}")
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter(run_id, correlation_id))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
