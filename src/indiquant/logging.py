import logging
import sys

import structlog

from indiquant.config.settings import IndiQuantSettings


def setup_logging(level: str | None = None) -> None:
    """Configure structured logging for the application."""
    if level is None:
        level = IndiQuantSettings().log_level

    shared_processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    processors: list[structlog.types.Processor]
    if sys.stderr.isatty():
        processors = [*shared_processors, structlog.dev.ConsoleRenderer()]
    else:
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    # Convert string level to int for stdlib filtering
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
    )
