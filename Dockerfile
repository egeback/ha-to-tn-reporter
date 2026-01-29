# Stage 1: Build stage
FROM python:3.12-slim as builder

# Avoid generating .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a local directory
COPY requirements.txt .
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install --prefix=/install -r requirements.txt && \
    pip install --prefix=/install --no-deps .

# Stage 2: Final runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (curl is required for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -u 1000 appuser

# Copy only the installed packages from the builder
COPY --from=builder /install /usr/local

# Copy the source code
COPY src/ /app/src/
COPY README.md /app/

# Create a directory for persistent state data
# Ensure appuser owns the application directory to allow writing state.json
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Build-time argument for versioning
ARG APP_VERSION=unknown

# Environment variables with defaults
ENV PYTHONPATH="/app/src" \
    # --- App Infrastructure ---
    APP_VERSION=$APP_VERSION \
    LOG_LEVEL="WARNING" \
    HEALTH_PORT="8080" \
    REPORTER_INTERVAL="180" \
    # --- Home Assistant ---
    REPORTER_HA_URL="" \
    REPORTER_HA_TOKEN="" \
    # --- Temperatur.nu ---
    REPORTER_TN_HASH="" \
    REPORTER_SENSOR_MAPPING="" \
    # --- MQTT Broker ---
    REPORTER_MQTT_HOST="localhost" \
    REPORTER_MQTT_PORT="1883" \
    REPORTER_MQTT_USER="" \
    REPORTER_MQTT_PASSWORD="" \
    REPORTER_MQTT_TOPIC="tn_reporter"

# Expose the health check port
EXPOSE 8080

# Healthcheck configuration
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:${HEALTH_PORT}/health || exit 1

# Switch to non-root user for security
USER appuser

# The command to run the application
# We use the module path to ensure imports work correctly
CMD ["python", "-m", "reporter.main"]