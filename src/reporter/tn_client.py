import logging
import httpx
from reporter.model.sensor import TempSensor

logger = logging.getLogger("reporter.tn_client")

async def report_to_tn(client: httpx.AsyncClient, sensor: TempSensor, value: float, tn_hash: str) -> bool:
    """
    Submits reading to TN API with robust error handling and debug logging.
    """
    params = {"id": sensor.tn_id, "t": f"{value:.1f}", "hash": tn_hash}
    url = "https://www.temperatur.nu/rapportera.php"
    
    logger.debug(f"Attempting TN report for station '{sensor.tn_id}' with value {value:.1f}°C")
    
    try:
        resp = await client.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        
        response_text = resp.text.strip().lower()
        if "ok" in response_text:
            logger.info(f"Successfully reported {value}°C to station '{sensor.tn_id}'")
            return True
        else:
            logger.error(f"TN API rejected data for '{sensor.tn_id}': {resp.text}")
            
    except Exception as e:
        logger.error(f"Error during TN reporting for '{sensor.tn_id}': {e}")
    
    return False