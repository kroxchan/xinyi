"""Loguru-based structured logging configuration."""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from datetime import datetime


def _make_console_streams_safe() -> None:
    """Avoid Windows console encoding errors when logs contain symbols."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            pass


def setup_logging(
    log_dir: str | None = None,
    log_level: str | None = None,
    rotation: str | None = None,
    retention: str | None = None,
    format_string: str | None = None,
) -> None:
    """Configure loguru with console + file output.

    Reads settings from src.config if not overridden.
    Dev mode (XINYI_ENV=dev) auto-upgrades log level to DEBUG.
    """
    _make_console_streams_safe()

    try:
        cfg = None
        try:
            from src.config import get_config
            cfg = get_config()
        except Exception:
            pass

        if log_level is None:
            log_level = "DEBUG" if (cfg and cfg.effective_log_level() == "DEBUG") else "INFO"
        if log_dir is None:
            log_dir = str(cfg.logging.dir) if cfg else "logs"
        if rotation is None:
            rotation = cfg.logging.rotation if cfg else "100 MB"
        if retention is None:
            retention = cfg.logging.retention if cfg else "30 days"
    except Exception:
        log_level = "INFO"
        log_dir = "logs"
        rotation = "100 MB"
        retention = "30 days"
    try:
        from loguru import logger
    except ImportError:
        # Fallback to standard logging if loguru not installed
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        return

    # Remove default handler
    logger.remove()

    # Console: INFO level, colored
    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        )

    logger.add(
        sys.stderr,
        level=log_level,
        format=format_string,
        colorize=True,
    )

    # File: DEBUG level
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / f"xinyi-{datetime.now().strftime('%Y-%m-%d')}.log"

    logger.add(
        log_path,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=rotation,
        retention=retention,
        compression="zip",
        diagnose=True,  # show variable names in tracebacks
    )

    # Suppress noisy third-party loggers
    for noisy in (
        "httpx",
        "openai",
        "chromadb",
        "urllib3",
        "sentence_transformers",
        "gradio",
        "gradio_server",
        "jieba",
        "uvicorn",
    ):
        logger.disable(noisy)

    # Sync loguru handlers to standard logging so that modules using
    # logging.getLogger(__name__) get the same output as loguru loggers
    _sync_loguru_to_standard_logging(log_level)


def _sync_loguru_to_standard_logging(log_level: str) -> None:
    """Mirror loguru's handlers into the standard logging hierarchy.

    This lets modules that call logging.getLogger(__name__) directly
    produce output through the same sinks (console + file) that loguru uses,
    with identical formatting.
    """
    root = logging.getLogger()
    if root.handlers:  # already synced
        return

    class _LoguruHandler(logging.Handler):
        """Bridge that re-emits standard log records into loguru."""

        def __init__(self, level: int) -> None:
            super().__init__(level=level)
            self._loguru = None

        def emit(self, record: logging.LogRecord) -> None:
            if self._loguru is None:
                from loguru import logger as _loguru

                self._loguru = _loguru
            try:
                self._loguru.log(
                    record.levelname,
                    self.format(record),
                )
            except Exception:
                self.handleError(record)

    handler = _LoguruHandler(getattr(logging, log_level.upper(), logging.INFO))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """Return a standard-library logger that streams through loguru's sinks.

    Unlike returning the global loguru logger (which ignores the ``name``
    argument and always attributes records to loguru internals), this returns
    a regular ``logging.Logger`` tied to the standard logging hierarchy.  Its
    messages are re-routed through a custom handler into loguru, so every
    logger benefitting from ``setup_logging()`` gets the same console and file
    output with the same formatting.
    """
    return logging.getLogger(name)
