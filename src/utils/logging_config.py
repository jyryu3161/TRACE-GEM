"""Logging configuration for the GEM Evaluator."""

import logging
import sys

from src.utils.constants import LOG_DIR


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("gem_evaluator")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(LOG_DIR / "gem_evaluator.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        )
    )
    logger.addHandler(file_handler)

    return logger
