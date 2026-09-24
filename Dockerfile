FROM python:3.12-slim

ARG BUILD_COMMIT=unknown
ARG BUILD_TAG=unknown
ARG BUILD_TIME=unknown
ARG BUILD_ENV=unknown
ENV BUILD_COMMIT=${BUILD_COMMIT} \
    BUILD_TAG=${BUILD_TAG} \
    BUILD_TIME=${BUILD_TIME} \
    BUILD_ENV=${BUILD_ENV}

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .

# Build check: the deploy fails if any write route (POST/PUT/PATCH/DELETE) has
# neither @audit_route(...) nor @no_audit(reason). It imports the app against
# a throwaway database, then the script and that database are removed.
COPY scripts/audit_route_coverage.py /tmp/audit-check/
RUN python /tmp/audit-check/audit_route_coverage.py --missing --server-dir /app \
    && rm -rf /tmp/audit-check /tmp/audit-coverage-*

COPY frontend/dist/ ./static/

EXPOSE 8000

# One process only (no --workers): live editing keeps shared state in memory.
# Pings keep live connections open through Fly's proxy, which drops idle ones.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "20", "--ws-ping-interval", "20", "--ws-ping-timeout", "20"]
