"""Small structured logging setup shared by each pipeline stage."""

import logging
from pathlib import Path


def make_logger(log_dir: Path, run_id: str) -> logging.LoggerAdapter:
    """Log to both console and file; run_id lets operators trace one execution."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("apex_pipeline")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s run_id=%(run_id)s %(message)s"
    )
    for handler in (logging.StreamHandler(), logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logging.LoggerAdapter(logger, {"run_id": run_id})


def close_logger(logger: logging.LoggerAdapter) -> None:
    """Release file handles before temporary run directories are removed."""
    for handler in list(logger.logger.handlers):
        handler.close()
        logger.logger.removeHandler(handler)
