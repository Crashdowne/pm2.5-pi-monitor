"""Entry point: ``python -m aqi_site``.

Loads config, starts the background alert poller, and serves the app with waitress.
"""
from __future__ import annotations

import logging
import threading

from waitress import serve

from . import alerts
from .api import create_app
from .config import load


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("aqi_site")
    config = load()
    app = create_app(config)

    stop_event = threading.Event()
    poller = threading.Thread(
        target=alerts.run_poller, args=(config, stop_event), name="alert-poller", daemon=True
    )
    poller.start()

    log.info("aqi-site serving on %s:%s (warehouse=%s)", config.host, config.port, config.db_path)
    try:
        serve(app, host=config.host, port=config.port, threads=8, ident="aqi-site")
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
