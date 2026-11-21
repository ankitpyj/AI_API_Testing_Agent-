"""
Structured JSON Logger & Contextual Telemetry for AI API Testing Agent.

Formats all application logs as structured JSON objects containing:
- timestamp (ISO-8601 UTC)
- level (INFO, WARNING, ERROR, etc.)
- message
- correlation_id / request_id
- worker_id
- module and function name
- optional context (user_id, project_id, run_id)
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Optional, Any, Dict

# Context variables for request-scoped correlation
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id_ctx", default=None)
user_id_ctx: ContextVar[Optional[int]] = ContextVar("user_id_ctx", default=None)
run_id_ctx: ContextVar[Optional[int]] = ContextVar("run_id_ctx", default=None)


class JSONFormatter(logging.Formatter):
    """Formats log records as structured, single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        # Include request correlation ID if available
        req_id = getattr(record, "request_id", None) or request_id_ctx.get()
        if req_id:
            log_payload["request_id"] = req_id

        # Include user context if available
        uid = getattr(record, "user_id", None) or user_id_ctx.get()
        if uid is not None:
            log_payload["user_id"] = uid

        # Include run context if available
        rid = getattr(record, "run_id", None) or run_id_ctx.get()
        if rid is not None:
            log_payload["run_id"] = rid

        # Include worker ID if worker context exists
        wid = getattr(record, "worker_id", None) or os.getenv("WORKER_ID")
        if wid:
            log_payload["worker_id"] = wid

        # Include exception trace if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


def setup_structured_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures the root and application loggers to output structured JSON."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    # Avoid duplicate handlers if re-called
    if not any(isinstance(h.formatter, JSONFormatter) for h in root_logger.handlers):
        root_logger.handlers = [handler]
        root_logger.setLevel(level)

    app_logger = logging.getLogger("agent_backend")
    app_logger.setLevel(level)
    return app_logger


logger = setup_structured_logging()
