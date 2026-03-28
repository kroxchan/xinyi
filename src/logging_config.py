"""Loguru-based structured logging configuration."""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from datetime import datetime


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
    for noisy in ("httpx", "openai", "chromadb", "urllib3", "sentence_transformers"):
        logger.disable(noisy)


def get_logger(name: str) -> "logger":
    """Return a loguru logger for the given module name."""
    try:
        from loguru import logger as _logger
        return _logger
    except ImportError:
        return logging.getLogger(name)
