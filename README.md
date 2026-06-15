# IoT Home AC Manager

An automatic Mitsubishi air conditioner (AC) manager daemon and control REST API. It integrates with the **MELCloud** platform to perform automated telemetry logging and provides HTTP endpoints for scheduled or transient AC control.

---

## Features

*   **Automated Telemetry Logging**: Periodically polls AC states (mode, temperatures, fan speeds, horizontal/vertical vanes, room CO2, and hourly energy consumption metrics) and saves them in daily CSV format (e.g. `log_YYYY-MM-DD.csv`).
*   **Direct AC Control**: Immediate POST control (`on`, `off`, `set` parameters) with built-in state redundancy filtering.
*   **Time-bound Transient Runs**: Turn a unit ON immediately and schedule an automatic shutdown using a single request (e.g., *turn ON until 03:00*).
*   **Scheduled Actions**: Schedule future ON/OFF actions at specific times (`at` or `until`).
*   **Diagnostic CLI Helper**: Access plain-text system summaries directly in the terminal via a GET command blueprint.

---

## Project Structure

The project has been modularized to separate concerns:

```
iot-home-manager/
├── iot_home_manager/          # Core Python Package
│   ├── __init__.py
│   ├── config.py              # Configuration & Environment Variables
│   ├── logger.py              # Background CSV logging routines
│   ├── timers.py              # Asynchronous timer executors
│   └── app.py                 # FastAPI Application & REST Endpoints
├── .env                       # Local environment variables (MELCloud credentials)
├── iot-home-manager.py        # Thin wrapper entrypoint to run the server
├── pyproject.toml             # Project dependency specifications
└── README.md
```

---

## Getting Started

### Method A: Docker (Recommended for Always-On/Edge Deployments)

This project supports **Docker Secrets** to isolate and protect credentials on disk.

1.  Create your secret files on the host system:
    ```bash
    mkdir -p secrets
    echo "your-melcloud-email" > secrets/melcloud_email
    echo "your-melcloud-password" > secrets/melcloud_password
    ```
2.  Start the container setup:
    ```bash
    docker compose up -d --build
    ```
    *   **Logs Persistence**: Telemetry CSV files are automatically created inside the container at `/app/logs` and persisted on the host machine in the `./logs` directory.
    *   **Port Access**: The API server is bound to host port `8000`.

---

### Method B: Local running with `uv`

1.  **Prerequisites**: Ensure you have [uv](https://github.com/astral-sh/uv) installed.
2.  **Configuration**: Create a `.env` file in the root directory:
    ```env
    MELCLOUD_EMAIL="your-email@example.com"
    MELCLOUD_PASSWORD="your-melcloud-password"
    LOG_INTERVAL=3600 # Polling interval in seconds (default 3600/hourly)
    SERVER_PORT=8000  # FastAPI listener port (default 8000)
    ```
3.  **Run the Server**: Run the daemon using `uv`:
    ```bash
    uv run iot-home-manager.py
    ```

---

## API & CLI Reference

Navigate to `http://127.0.0.1:8000/docs` in your browser for the interactive Swagger UI.

### Key Endpoint Blueprint

*   **System Status Check**:
    ```bash
    curl -X GET "http://127.0.0.1:8000/status"
    ```
*   **Turn Unit 0 ON (Temp = 22°C, Vanes Swing)**:
    ```bash
    curl -X POST "http://127.0.0.1:8000/control/0/on?temp=22&vane_h=swing&vane_v=auto"
    ```
*   **Turn Unit 0 ON and Schedule OFF at 03:00**:
    ```bash
    curl -X POST "http://127.0.0.1:8000/control/0/on-until?until=03:00&temp=24&mode=dry"
    ```
*   **Schedule OFF timer at 02:30**:
    ```bash
    curl -X POST "http://127.0.0.1:8000/control/0/timer/off?until=02:30"
    ```
*   **Schedule ON timer at 07:30**:
    ```bash
    curl -X POST "http://127.0.0.1:8000/control/0/timer/on?at=07:30&temp=24&vane_h=1"
    ```
