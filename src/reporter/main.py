import os
import asyncio
import logging
import time
from datetime import datetime, timezone
import argparse
import httpx
import sys
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

def parse_args(args_list=None):
    """
    Defines the CLI and Environment Variable schema.
    Priority: CLI Argument > Environment Variable > Default.
    """
    parser = argparse.ArgumentParser(description="HA to Temperatur.nu Reporter")
    
    # Home Assistant Source Settings
    parser.add_argument("--ha-url", default=os.getenv("REPORTER_HA_URL"), 
                        help="HA API URL (e.g. http://192.168.1.10:8123)")
    parser.add_argument("--ha-token", default=os.getenv("REPORTER_HA_TOKEN"), 
                        help="HA Long-Lived Access Token")
    
    # Temperatur.nu Destination Settings
    parser.add_argument("--tn-hash", default=os.getenv("REPORTER_TN_HASH"), 
                        help="Reporting hash from temperatur.nu")
    parser.add_argument("--mapping", default=os.getenv("REPORTER_SENSOR_MAPPING"), 
                        help="Mapping: tn_id=ha_id|ha_id")
    
    # App Infrastructure Settings
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HEALTH_PORT", 8080)))
    parser.add_argument("--interval", type=int, default=int(os.getenv("REPORTER_INTERVAL", 180)),
                        help="Reporting interval in seconds (default: 180)")

    # MQTT Settings
    parser.add_argument("--mqtt-host", default=os.getenv("REPORTER_MQTT_HOST"),
                        help="MQTT broker hostname")
    parser.add_argument("--mqtt-port", type=int, default=int(os.getenv("REPORTER_MQTT_PORT", 1883)),
                        help="MQTT broker port")
    parser.add_argument("--mqtt-user", default=os.getenv("REPORTER_MQTT_USER"),
                        help="MQTT username")
    parser.add_argument("--mqtt-password", default=os.getenv("REPORTER_MQTT_PASSWORD"),
                        help="MQTT password")
    
    return parser.parse_args(args_list)

# Define global logger
logger = logging.getLogger("reporter.main")

# Internal imports
from reporter.state import health_status, update_success, update_error
from reporter.web import start_health_server
from reporter.mqtt import MQTTManager
from reporter.config import parse_sensors
from reporter.tn_client import report_to_tn

async def main_loop():
    """
    Orchestrates sensors, MQTT, and Web server using a Producer-Consumer queue.
    """
    running_tasks = set()
    args = parse_args()

    # Configure Logging
    logging.basicConfig(
        level=args.log_level.upper(),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True 
    )
    
    if not all([args.ha_url, args.ha_token, args.tn_hash, args.mapping]):
        logger.critical("Initialization failed: Missing required REPORTER_* configuration.")
        sys.exit(1)

    # Parse Sensors
    sensors = []
    try:
        sensors = parse_sensors(args.mapping, args.ha_url, args.ha_token)
    except Exception as e:
        logger.critical(f"Fatal error parsing sensor mapping: {e}")
        sys.exit(1)

    # 1. Initialize MQTT Manager (The Consumer)
    mqtt = None
    if args.mqtt_host:
        mqtt = MQTTManager(
            host=args.mqtt_host,
            port=args.mqtt_port,
            sensors=sensors,
            username=args.mqtt_user,
            password=args.mqtt_password
        )
        
        # Start MQTT in the background and protect from Garbage Collection
        mqtt_task = asyncio.create_task(mqtt.run())
        running_tasks.add(mqtt_task)
        mqtt_task.add_done_callback(running_tasks.discard)
    else:
        logger.info("MQTT Host not configured. MQTT reporting disabled.")
    
    # 2. Start Health Server
    logger.info(f"Starting health server on port {args.port}...")
    await start_health_server(mqtt, port=args.port)

    # 3. Main Reporting Loop (The Producer)
    logger.info("Service started. Entering main reporting loop.")
    async with httpx.AsyncClient() as client:
        while True:
            logger.debug("--- New Reporting Cycle Started ---")
            
            for sensor in sensors:
                try:
                    val, stats = await sensor.fetch_data(client)
                    health_status[sensor.tn_id] = stats
                    
                    if val is not None:
                        health_status[sensor.tn_id]["last_reported_value"] = val
                        if await report_to_tn(client, sensor, val, args.tn_hash):
                            update_success()
                        else:
                            update_error()
                    else:
                        logger.warning(f"Station '{sensor.tn_id}' skipped: {stats.get('error', 'Unusable data')}")
                        update_error()
                        
                except Exception as e:
                    logger.exception(f"Unhandled error for sensor '{sensor.tn_id}': {e}")
                    update_error()
            
            # Mark the end of the fetch cycle
            health_status["last_ha_fetch"] = time.time()

            # --- TRIGGER MQTT UPDATE ---
            # Create a clean payload for the MQTT queue, separating global stats
            # from per-station data to ensure a clean data contract.
            
            # 1. Gather global statistics
            uptime_seconds = int(time.time() - health_status["session_start_time"])
            
            # Calculate aggregated sensor stats across all stations
            global_active_sensors = 0
            global_total_sensors = 0
            
            for s in sensors:
                if s.tn_id in health_status and isinstance(health_status[s.tn_id], dict):
                    s_stats = health_status[s.tn_id]
                    global_active_sensors += s_stats.get("active_sensors", 0)
                    global_total_sensors += s_stats.get("total_sensors", 0)
            
            global_invalid_sensors = global_total_sensors - global_active_sensors
            
            # Format timestamps into ISO 8601 strings with timezone
            start_time_iso = datetime.fromtimestamp(health_status["session_start_time"], tz=timezone.utc).isoformat(sep=' ', timespec='seconds')
            last_report_iso = None
            if health_status["last_successful_report"]:
                last_report_iso = datetime.fromtimestamp(health_status["last_successful_report"], tz=timezone.utc).isoformat(sep=' ', timespec='seconds')

            last_run_iso = datetime.fromtimestamp(health_status["last_ha_fetch"], tz=timezone.utc).isoformat(sep=' ', timespec='seconds')

            mqtt_stats_payload = {
                "status": health_status["status"],
                "version": health_status["version"],
                "uptime_seconds": uptime_seconds,
                "session_start_time_iso": start_time_iso,
                "session_success": health_status["session_success_count"],
                "lifetime_success": health_status["lifetime_success_count"],
                "session_errors": health_status["error_count"],
                "lifetime_errors": health_status["lifetime_error_count"],
                "last_successful_report": last_report_iso,
                "active_sensors": global_active_sensors,
                "invalid_sensors": global_invalid_sensors,
                "last_run": last_run_iso
            }

            # 2. Gather data for each configured station
            station_payload = {}
            for s in sensors:
                if s.tn_id in health_status and isinstance(health_status[s.tn_id], dict):
                    station_payload[s.tn_id] = health_status[s.tn_id]

            # 3. Combine and push to the queue for background processing
            if mqtt:
                mqtt.put_update({
                    "stats": mqtt_stats_payload,
                    "stations": station_payload
                })

            logger.debug(f"Cycle complete. Sleeping for {args.interval} seconds.")
            await asyncio.sleep(args.interval)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Service shutdown via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        sys.exit(1)