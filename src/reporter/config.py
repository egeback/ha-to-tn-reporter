import argparse
import os
import logging
from reporter.model.sensor import TempSensor

logger = logging.getLogger("reporter.config")

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
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "WARNING"))
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
    parser.add_argument("--mqtt-topic", default=os.getenv("REPORTER_MQTT_TOPIC", "tn_reporter"),
                        help="MQTT base topic (default: tn_reporter)")

    # Aggregation & bad-value protection
    parser.add_argument("--mode", default=os.getenv("REPORTER_CALCULATION_MODE", "min"),
                        choices=["min", "median", "mean"],
                        help="Aggregation mode across sensors in a group (default: min)")
    parser.add_argument("--max-age", type=int, default=int(os.getenv("REPORTER_MAX_AGE", 1800)),
                        help="Drop sensors whose last_updated is older than this many seconds (default: 1800)")
    parser.add_argument("--temp-min", type=float, default=float(os.getenv("REPORTER_TEMP_MIN", -50.0)),
                        help="Hard sanity floor in °C; readings below this are dropped (default: -50)")
    parser.add_argument("--temp-max", type=float, default=float(os.getenv("REPORTER_TEMP_MAX", 60.0)),
                        help="Hard sanity ceiling in °C; readings above this are dropped (default: 60)")
    parser.add_argument("--outlier-threshold-high", type=float,
                        default=float(os.getenv("REPORTER_OUTLIER_THRESHOLD_HIGH", 15.0)),
                        help="Drop sensors more than this many °C ABOVE the group median (default: 15)")
    parser.add_argument("--outlier-threshold-low", type=float,
                        default=float(os.getenv("REPORTER_OUTLIER_THRESHOLD_LOW", 25.0)),
                        help="Drop sensors more than this many °C BELOW the group median (default: 25; lenient on purpose so shade sensors survive a mostly-sunny group)")
    parser.add_argument("--outlier-min-group", type=int,
                        default=int(os.getenv("REPORTER_OUTLIER_MIN_GROUP", 3)),
                        help="Skip outlier rejection when fewer than this many valid sensors remain (default: 3)")

    return parser.parse_args(args_list)

def parse_sensors(mapping_config: str, ha_url: str, ha_token: str,
                  mode: str = "min", max_age: int = 1800,
                  temp_min: float = -50.0, temp_max: float = 60.0,
                  outlier_threshold_high: float = 15.0,
                  outlier_threshold_low: float = 25.0,
                  outlier_min_group: int = 3) -> list[TempSensor]:
    """
    Parses the sensor mapping string into a list of TempSensor objects.
    Includes defensive logic to fix common configuration errors.
    """
    sensors = []
    # Defensive check: Remove variable name if accidentally included in the value
    if mapping_config and mapping_config.startswith("REPORTER_SENSOR_MAPPING="):
        mapping_config = mapping_config.replace("REPORTER_SENSOR_MAPPING=", "", 1)
        logger.warning("Configuration Error: 'REPORTER_SENSOR_MAPPING=' found in value. Auto-correcting.")

    if not mapping_config:
        return sensors

    for item in mapping_config.split(','):
        if '=' not in item: continue
        tn_id, ha_ids = item.split('=', 1)
        sensors.append(TempSensor(
            ha_ids, tn_id, ha_url, ha_token,
            mode=mode, max_age=max_age,
            temp_min=temp_min, temp_max=temp_max,
            outlier_threshold_high=outlier_threshold_high,
            outlier_threshold_low=outlier_threshold_low,
            outlier_min_group=outlier_min_group,
        ))

    return sensors