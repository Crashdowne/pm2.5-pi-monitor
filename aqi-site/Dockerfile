# Multi-stage build for crashdowne/pi-aqi-monitor.
# Build from the REPO ROOT so the image can reuse the pm25 AQI module:
#   docker build -f aqi-site/Dockerfile -t crashdowne/pi-aqi-monitor .

# --- stage 1: build the Vite + TS + ECharts dashboard ---
FROM node:22-alpine AS web
WORKDIR /web
COPY aqi-site/web/package.json aqi-site/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY aqi-site/web/ ./
RUN npm run build

# --- stage 2: python runtime ---
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/app/aqi-site \
    AQI_SITE_DB=/data/pm25.db \
    AQI_SITE_STATE_DB=/state/aqi-site-state.db \
    AQI_SITE_HOST=0.0.0.0 \
    AQI_SITE_PORT=8080
WORKDIR /app

RUN pip install --no-cache-dir "flask>=3.0" "waitress>=3.0" "requests>=2.31"

# Reuse the core EPA AQI module (single source of truth) + the sidecar package.
COPY src/pm25/ ./src/pm25/
COPY aqi-site/aqi_site/ ./aqi-site/aqi_site/
COPY --from=web /web/dist/ ./aqi-site/web/dist/

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aqi \
    && mkdir -p /data /state && chown aqi /state
USER aqi

EXPOSE 8080
VOLUME ["/data", "/state"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 3).close()"

CMD ["python", "-m", "aqi_site"]
