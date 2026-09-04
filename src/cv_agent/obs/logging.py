"""structlog JSON para Cloud Logging.

`merge_contextvars` es lo que liga cada log al `request_id` que ata `api/middleware.py` — sin
tocar la firma de ninguna función intermedia."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog


def gcp_processor(
    logger: Any, name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    event_dict["severity"] = str(event_dict.pop("level", "info")).upper()
    event_dict["message"] = event_dict.pop("event", "")
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            gcp_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
