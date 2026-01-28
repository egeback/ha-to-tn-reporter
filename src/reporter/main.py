import os
import asyncio
import logging
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
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"), 
                        help="Logging level: DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--port", type=int, default=int(os.getenv("HEALTH_PORT", 8080)), 
                        help="Health check server port")
    parser.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", "localhost"),
                        help="MQTT broker hostname")
    
    return parser.parse_args(args_list)

# Define global logger; configuration happens inside main_loop
logger = logging.getLogger("reporter.main")

# Internal imports
from reporter.model.sensor import TempSensor
from reporter.state import health_status, update_success, update_error
from reporter.web import start_health_server
from reporter.mqtt import MQTTManager

async def report_to_tn(client: httpx.AsyncClient, sensor: TempSensor, value: float, tn_hash: str):
    """
    Submits reading to TN API with robust error handling and debug logging.
    """
    params = {"id": sensor.tn_id, "t": f"{value:.1f}", "hash": tn_hash}
    url = "http://www.temperatur.nu/rapportera.php"
    
    logger.debug(f"Attempting TN report for station '{sensor.tn_id}' with value {value:.1f}°C")
    
    try:
        resp = await client.get(url, params=params, timeout=10.0)
        resp.raise_for_status() # Raise exception for 4xx/5xx errors
        
        response_text = resp.text.strip().lower()
        if "ok" in response_text:
            logger.info(f"Successfully reported {value}°C to station '{sensor.tn_id}'")
            logger.debug(f"TN API Response: {resp.text}")
            return True
        else:
            logger.error(f"TN API rejected data for '{sensor.tn_id}': {resp.text}")
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from TN API for '{sensor.tn_id}': {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Network request failed for '{sensor.tn_id}': {e}")
    except Exception as e:
        logger.exception(f"Unexpected error during TN reporting for '{sensor.tn_id}': {e}")
    
    return False

async def main_loop():
    """
    Orchestrates sensors, MQTT, and Web server with extensive debug hooks.
    """
    args = parse_args()

    # Configure Logging
    logging.basicConfig(
        level=args.log_level.upper(),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True # Ensures our config overrides any library defaults
    )
    
    logger.debug("Debug logging enabled. Initializing components...")

    if not all([args.ha_url, args.ha_token, args.tn_hash, args.mapping]):
        logger.critical("Initialization failed: Missing required REPORTER_* configuration.")
        sys.exit(1)

    # Parse Sensors with error handling for malformed mapping strings
    sensors = []
    try:
        for item in args.mapping.split(','):
            if '=' not in item:
                logger.warning(f"Skipping malformed mapping segment: '{item}'")
                continue
            tn_id, ha_ids = item.split('=', 1)
            sensors.append(TempSensor(ha_ids, tn_id, args.ha_url, args.ha_token))
            logger.debug(f"Initialized sensor mapping: {tn_id} -> {ha_ids}")
    except Exception as e:
        logger.critical(f"Fatal error parsing sensor mapping: {e}")
        sys.exit(1)

    # Initialize Services
    logger.info(f"Connecting to MQTT broker at {args.mqtt_host}...")
    mqtt = MQTTManager(host=args.mqtt_host, sensors=sensors)
    asyncio.create_task(mqtt.run())
    
    logger.info(f"Starting health server on port {args.port}...")
    await start_health_server(mqtt, port=args.port)

    # Main Cycle
    logger.info("Service started. Entering main reporting loop.")
    async with httpx.AsyncClient() as client:
        while True:
            logger.debug("--- New Reporting Cycle Started ---")
            
            for sensor in sensors:
                try:
                    val, stats = await sensor.fetch_data(client)
                    health_status[sensor.tn_id] = stats
                    
                    if val is not None:
                        # Success path
                        health_status[sensor.tn_id]["last_reported_value"] = val
                        if await report_to_tn(client, sensor, val, args.tn_hash):
                            update_success()
                        else:
                            update_error()
                    else:
                        # Fetch succeeded but data was unusable (e.g., stale)
                        logger.warning(f"Station '{sensor.tn_id}' skipped: {stats.get('error', 'Unknown logic error')}")
                        update_error()
                        
                except Exception as e:
                    logger.exception(f"Unhandled error in cycle for sensor '{sensor.tn_id}': {e}")
                    update_error()
            
            logger.debug("Cycle complete. Sleeping for 180 seconds.")
            await asyncio.sleep(180)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Service shutdown via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        sys.exit(1)