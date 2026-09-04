"""Web entrypoint: serve the Flask app with waitress (lightweight, single process)."""
from __future__ import annotations

import argparse
import logging

from waitress import serve

from .api import create_app
from .config import load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="PM2.5 dashboard web server")
    ap.add_argument("--config", default="/etc/pm25/config.toml")
    args = ap.parse_args()
    cfg = load_config(args.config)
    app = create_app(cfg)
    logging.info("serving on %s:%d", cfg.web.host, cfg.web.port)
    serve(app, host=cfg.web.host, port=cfg.web.port, threads=4)


if __name__ == "__main__":
    main()
