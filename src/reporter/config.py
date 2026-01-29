import logging
from reporter.model.sensor import TempSensor

logger = logging.getLogger("reporter.config")

def parse_sensors(mapping_config: str, ha_url: str, ha_token: str) -> list[TempSensor]:
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
        sensors.append(TempSensor(ha_ids, tn_id, ha_url, ha_token))
    
    return sensors