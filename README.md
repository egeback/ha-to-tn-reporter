# HA to Temperatur.nu Reporter 🌡️

![Tests](https://github.com/YOUR_USERNAME/YOUR_REPO_NAME/actions/workflows/tests.yml/badge.svg)

An asynchronous Python service that aggregates Home Assistant temperature sensors and reports them to [temperatur.nu](https://www.temperatur.nu). Designed for high reliability with persistent success tracking and Home Assistant MQTT Discovery.

---

## 🏗 Project Structure

The project follows a modular, decoupled architecture to ensure high reliability, easy maintenance, and clean testing.



```text
.
├── .env                  # Private secrets (ignored by git)
├── .env.example          # Template for configuration
├── .gitignore            # Git exclusion rules
├── compose.yaml          # Container orchestration
├── Dockerfile            # Multi-arch build definition
├── pyproject.toml        # Build system and dependencies
├── README.md             # Documentation
├── build.sh              # Multi-arch build script (amd64/arm64)
├── data/                 # Persistent storage (created at runtime)
├── src/
│   └── reporter/
│       ├── __init__.py
│       ├── config.py     # Configuration parsing logic
│       ├── main.py       # Orchestrator & CLI entry point
│       ├── mqtt.py       # MQTT connection, Discovery & LWT logic
│       ├── state.py      # Persistence & Global Metric management
│       ├── tn_client.py  # Temperatur.nu API client
│       ├── web.py        # Health Check HTTP server
│       └── model/
│           ├── __init__.py
│           └── sensor.py # Core logic for HA fetching & aggregation
└── tests/                # Test suite
    ├── test_api.py
    ├── test_config.py
    ├── test_main.py
    ├── test_mqtt.py
    └── test_sensor.py
---

## 🚀 Getting Started

### 1. Configuration (`.env`)

Copy the `.env.example` file to `.env` and fill in your credentials. The application uses these variables to connect to your local services and the external API.

```bash
# HA Config
REPORTER_HA_URL=[http://192.168.1.](http://192.168.1.)XX:8123
REPORTER_HA_TOKEN=your_token

# TN Config
REPORTER_TN_HASH=your_hash
# Format: station_id=ha_sensor_id
# - Use a pipe (|) to group multiple HA sensors for one station.
# - Use a comma (,) to configure multiple stations.
REPORTER_SENSOR_MAPPING=sandbyang=sensor.outside_1|sensor.outside_2,garage=sensor.garage_temp

# MQTT Config
REPORTER_MQTT_HOST=192.168.1.XX
REPORTER_MQTT_USER=user
REPORTER_MQTT_PASSWORD=pass

```

### 2. Run with Docker Compose

The recommended way to deploy is using Docker. This ensures the environment is consistent and the service restarts automatically.

```bash
docker-compose up -d

```

---

## 📡 Monitoring & Health

### Health Check

The service exposes a JSON health report on port `8080`. This is used by Docker's healthcheck mechanism to monitor the MQTT connection.

```bash
curl http://localhost:8080/health

```

### MQTT Discovery

This service automatically creates entities in Home Assistant.

* **State**: The calculated temperature value.
* **Attributes**: Detailed metadata including `session_success`, `lifetime_success` (persistent odometer), and `stale_sensor_count`.
* **Availability**: Uses MQTT Last Will (LWT) to show "Unavailable" if the container stops.

---

## 🛠 Development & Contributing

### Setup Environment

1. Clone the repository.
2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate

```


3. Install in editable mode with development/test dependencies:
```bash
pip install -e .[test]

```



### Running Tests

We use `pytest` with `respx` for API mocking. Contributions must pass all existing tests.

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=reporter

```

---

## 📦 Multi-Arch Builds

To build and push images for both **amd64** and **arm64** (e.g., Raspberry Pi) using Docker Buildx:

```bash
chmod +x build.sh
./build.sh

```

---

## 📜 License

MIT License. See `LICENSE` for details.

```

---