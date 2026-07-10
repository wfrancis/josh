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
COPY frontend/dist/ ./static/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
