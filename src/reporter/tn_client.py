import asyncio
import logging
import httpx
from reporter.model.sensor import TempSensor

logger = logging.getLogger("reporter.tn_client")

# Retry tuning for transient failures (timeouts, 5xx, connection resets).
# The main loop already cycles every REPORTER_INTERVAL seconds, so we keep
# retries short — just enough to ride out a brief blip at temperatur.nu.
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (2, 5)  # delay before attempt 2 and attempt 3


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return isinstance(exc, httpx.RequestError)


async def report_to_tn(client: httpx.AsyncClient, sensor: TempSensor, value: float, tn_hash: str) -> bool:
    """
    Submits reading to TN API with robust error handling and debug logging.
    Retries transient failures (timeouts / 5xx) up to _MAX_ATTEMPTS times.
    """
    params = {"id": sensor.tn_id, "t": f"{value:.1f}", "hash": tn_hash}
    url = "https://www.temperatur.nu/rapportera.php"

    logger.debug(f"Attempting TN report for station '{sensor.tn_id}' with value {value:.1f}°C")

    last_error_desc = "unknown"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            resp.raise_for_status()

            response_text = resp.text.strip().lower()
            if "ok" in response_text:
                logger.info(f"Successfully reported {value}°C to station '{sensor.tn_id}'")
                return True

            # Non-transient: API rejected our payload (bad hash, bad id, etc.). No retry.
            logger.error(f"TN API rejected data for '{sensor.tn_id}': {resp.text}")
            return False

        except Exception as e:
            transient = _is_transient(e)
            # str(e) is empty for some httpx errors — log the type so we know what happened.
            last_error_desc = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__

            if transient and attempt < _MAX_ATTEMPTS:
                backoff = _BACKOFF_SECONDS[attempt - 1]
                logger.warning(
                    f"TN report attempt {attempt}/{_MAX_ATTEMPTS} for '{sensor.tn_id}' failed "
                    f"({last_error_desc}). Retrying in {backoff}s."
                )
                await asyncio.sleep(backoff)
                continue

            logger.error(
                f"Error during TN reporting for '{sensor.tn_id}' "
                f"(attempt {attempt}/{_MAX_ATTEMPTS}): {last_error_desc}"
            )
            return False

    return False
