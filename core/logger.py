"""
core/logger.py
--------------
Centralised logging configuration for FacilityOps Pulse.

Call `setup_logging()` once from app.py at startup.
All other modules simply do `logging.getLogger(__name__)`.

Log output:
  - Console: coloured, human-readable (INFO and above)
  - File:    rotating JSON-like lines (all levels from DEBUG upward in dev)
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


class _ColourFormatter(logging.Formatter):
    """
    A simple formatter that adds ANSI colour codes to console output.
    Falls back to plain text on platforms that don't support ANSI.
    """

    LEVEL_COLOURS = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[1;31m",# Bold red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLOURS.get(record.levelno, "")
        record.levelname = f"{colour}{record.levelname:<8}{self.RESET}"
        return super().format(record)


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/facilityops.log",
) -> None:
    """
    Configure root logger with console and rotating-file handlers.

    Parameters
    ----------
    log_level : str
        Minimum level to emit. Comes from settings.LOG_LEVEL.
    log_file : str
        Path to the rotating log file. Parent directory is created if needed.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # root captures everything; handlers filter

    # Avoid adding duplicate handlers if setup_logging is called more than once
    if root.handlers:
        return

    # ------------------------------------------------------------------ #
    # Console handler
    # ------------------------------------------------------------------ #
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)

    use_colour = (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and os.name != "nt"  # disable colour on Windows cmd/powershell by default
    )
    console_fmt = "%(asctime)s %(levelname)s %(name)s — %(message)s"
    if use_colour:
        console_handler.setFormatter(
            _ColourFormatter(console_fmt, datefmt="%H:%M:%S")
        )
    else:
        console_handler.setFormatter(
            logging.Formatter(console_fmt, datefmt="%H:%M:%S")
        )
    root.addHandler(console_handler)

    # ------------------------------------------------------------------ #
    # Rotating file handler
    # ------------------------------------------------------------------ #
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    # ------------------------------------------------------------------ #
    # Silence noisy third-party loggers
    # ------------------------------------------------------------------ #
    for noisy in (
        "urllib3",
        "httpx",
        "httpcore",
        "sentence_transformers",
        "transformers",
        "torch",
        "filelock",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — level=%s, file=%s", log_level, log_file
    )


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper; equivalent to logging.getLogger(name)."""
    return logging.getLogger(name)
