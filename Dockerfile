# Stage 1: Build stage
FROM python:3.11-slim as builder

# Avoid generating .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a local directory
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install --prefix=/install .

# Stage 2: Final runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed packages from the builder
COPY --from=builder /install /usr/local

# Copy the source code
COPY src/ /app/src/
COPY README.md /app/

# Create a directory for persistent state data
RUN mkdir -p /app/data

# Environment variables with defaults
ENV REPORTER_HA_URL="" \
    REPORTER_HA_TOKEN="" \
    REPORTER_TN_HASH="" \
    REPORTER_SENSOR_MAPPING="" \
    PYTHONPATH="/app/src"

# Expose the health check port
EXPOSE 8080

# The command to run the application
# We use the module path to ensure imports work correctly
CMD ["python", "-m", "reporter.main"]