# Multi-stage: build the Vue frontend, then run the FastAPI backend serving it.
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend
RUN pip install --no-cache-dir uv
WORKDIR /app
# Runtime deps only (production broker is Mosquitto, so amqtt dev-broker is omitted).
RUN uv pip install --system --no-cache \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "aiomqtt>=2.3" "pydantic>=2.7"
COPY server/ ./server/
COPY sim/ ./sim/
COPY --from=frontend /fe/dist ./frontend/dist
ENV BROKER_HOST=mosquitto BROKER_PORT=1883 PORT=8077
EXPOSE 8077
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8077"]
