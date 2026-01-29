import json
import os
import time
import logging

from . import __version__

# Initialize logger for the state module to track persistence events
logger = logging.getLogger("reporter.state")

# Path where the stats are stored to survive container restarts/rebuilds
# Ensure this file is mapped to a persistent volume in Docker
STATE_FILE = "state.json"

# --- The Global Health Status Object ---
# This dictionary is the 'Single Source of Truth' for the application.
# It is shared across the main loop, the web health server, and the MQTT manager.
health_status = {
    "status": "starting",           # Current operational state
    "mqtt_connected": False,        # Tracked by mqtt.py
    "last_ha_fetch": None,          # Float timestamp of last HA fetch cycle
    "last_successful_report": None, # Float timestamp of last successful TN report
    "session_success_count": 0,     # Reset every time the app starts
    "lifetime_success_count": 0,    # Loaded from and saved to state.json
    "lifetime_error_count": 0,      # Loaded from and saved to state.json
    "error_count": 0,               # Network or API failures in this session
    "session_start_time": time.time(),
    "version": __version__
}

def save_state():
    """
    Writes the lifetime metrics to the local disk.
    
    This function is called after every successful report to ensure that 
    the 'Lifetime Success' counter is preserved even if the process crashes.
    """
    try:
        # We only persist the lifetime count to minimize disk I/O wear
        data_to_save = {
            "lifetime_success_count": health_status["lifetime_success_count"],
            "lifetime_error_count": health_status["lifetime_error_count"]
        }
        with open(STATE_FILE, "w") as f:
            json.dump(data_to_save, f)
        
        logger.debug(f"State persisted: {data_to_save}")
    except Exception as e:
        logger.error(f"Critical: Could not save state.json: {e}")

def load_state():
    """
    Attempts to read state.json from the project root.
    If the file exists, it restores the lifetime_success_count to the global dictionary.
    """
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                saved_data = json.load(f)
                # Update the global dict with the value from disk
                health_status["lifetime_success_count"] = saved_data.get("lifetime_success_count", 0)
                health_status["lifetime_error_count"] = saved_data.get("lifetime_error_count", 0)
                logger.info(f"Persistence: Loaded {health_status['lifetime_success_count']} lifetime successes.")
                logger.info(f"Persistence: Loaded {health_status['lifetime_error_count']} lifetime errors.")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Persistence: Failed to load state.json (corrupt or inaccessible): {e}")
    else:
        logger.debug("Persistence: No state.json found. Initializing new lifetime counter.")

def update_success():
    """
    Helper function to be called by main.py after a successful temperatur.nu report.
    Increments counts, updates status, and triggers a disk save.
    """
    health_status["session_success_count"] += 1
    health_status["lifetime_success_count"] += 1
    health_status["status"] = "running"
    health_status["last_successful_report"] = time.time()
    
    # Save to disk immediately so we don't lose the count on a crash
    save_state()

def update_error():
    """
    Helper function to be called when an API or network error occurs.
    Updates the operational status to alert monitoring systems.
    """
    health_status["error_count"] += 1
    health_status["lifetime_error_count"] += 1
    health_status["status"] = "error"
    logger.debug(f"State updated: Error encountered. Total session errors: {health_status['error_count']}")

    # Persist lifetime error count
    save_state()

# --- Automatic Initialization ---
# This runs once when the module is first imported (usually by main.py)
load_state()