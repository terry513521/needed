"""Central logging setup for the dashboard API (see DASHBOARD_LOG_LEVEL in `.env`)."""

from __future__ import annotations

import logging
import os
import sys


def _enable_dashboard_logger_tree() -> None:
    """
    Uvicorn applies logging.config with disable_existing_loggers; loggers created during
    import (e.g. dashboard.*) end up disabled. Re-enable them so records reach handlers.
    """
    # Known names from our package; also any child already registered on the manager.
    mgr = logging.root.manager
    for name in list(mgr.loggerDict.keys()):
        if not isinstance(name, str):
            continue
        if name == "dashboard" or name.startswith("dashboard."):
            logging.getLogger(name).disabled = False


def configure_dashboard_logging() -> None:
    """
    Attach a stderr handler to the `dashboard` logger.

    Call this from FastAPI lifespan **after** the worker starts (so it runs after uvicorn's
    logging setup). Env:

      DASHBOARD_LOG_LEVEL — DEBUG, INFO, WARNING, ERROR (default INFO)
      DASHBOARD_LOG_FORMAT — optional pattern for logging.Formatter
    """
    level_name = os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.environ.get(
        "DASHBOARD_LOG_FORMAT",
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    datefmt = os.environ.get("DASHBOARD_LOG_DATEFMT", "%Y-%m-%d %H:%M:%S")

    _enable_dashboard_logger_tree()

    dash = logging.getLogger("dashboard")
    dash.setLevel(level)
    dash.disabled = False
    dash.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    dash.addHandler(handler)
    dash.propagate = False

    if level <= logging.DEBUG:
        logging.getLogger("urllib3.connectionpool").setLevel(logging.DEBUG)
    else:
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
