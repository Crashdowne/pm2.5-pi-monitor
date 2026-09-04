"""aqi-site: read-only analytics + mask-advisor sidecar for the PM2.5 warehouse.

Reads the SQLite warehouse written by ``server/ingest.py`` (never writes to it) and
serves a rich ECharts dashboard plus an asthma-aware mask advisor over the tailnet.
"""

__version__ = "0.1.0"
