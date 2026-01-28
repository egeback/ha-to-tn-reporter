import logging
import statistics
from datetime import datetime, timezone

logger = logging.getLogger("reporter.sensor")

class TempSensor:
    """
    Represents a group of one or more Home Assistant sensors mapped to one Temperatur.nu ID.
    Handles data fetching, age-validation (stale data), and mathematical aggregation.
    """
    def __init__(self, ha_ids, tn_id, ha_url, ha_token, mode="min", max_age=1800):
        self.ha_ids = ha_ids.split('|') # Supports pipe-separated IDs: "sensor.a|sensor.b"
        self.tn_id = tn_id
        self.ha_url = ha_url
        self.ha_token = ha_token
        self.mode = mode
        self.max_age = max_age # Default 30 minutes (1800 seconds)

    def _calculate_aggregation(self, values):
        """
        Internal math engine. Performs min, median, or mean on a list of floats.
        Returns None if the list is empty.
        """
        if not values:
            return None
        
        if self.mode == "min":
            return min(values)
        elif self.mode == "median":
            return statistics.median(values)
        else:  # Fallback to arithmetic mean
            return statistics.mean(values)

    async def fetch_data(self, client):
        """
        Requests the state of each HA sensor in the group.
        Filters out sensors that are 'unavailable', 'unknown', or older than max_age.
        Returns (aggregated_value, statistics_dictionary).
        """
        valid_values = []
        stale_count = 0
        headers = {"Authorization": f"Bearer {self.ha_token}"}

        for eid in self.ha_ids:
            try:
                logger.debug(f"Fetching {eid} from Home Assistant")
                resp = await client.get(f"{self.ha_url}/api/states/{eid}", headers=headers, timeout=5.0)
                
                if resp.status_code != 200:
                    logger.error(f"HA returned {resp.status_code} for {eid}")
                    continue

                data = resp.json()
                state = data.get("state")
                
                # Skip sensors that aren't currently reporting a numeric value
                if state in ["unavailable", "unknown", None]:
                    logger.debug(f"Sensor {eid} is currently in an unknown/unavailable state.")
                    continue

                # Age Validation Logic
                # HA timestamps usually end in 'Z'. Replace with '+00:00' for standard ISO parsing.
                ts_str = data["last_updated"].replace("Z", "+00:00")
                last_updated = datetime.fromisoformat(ts_str)
                age = (datetime.now(timezone.utc) - last_updated).total_seconds()

                if age > self.max_age:
                    logger.warning(f"Sensor {eid} is stale (age: {int(age)}s > limit: {self.max_age}s).")
                    stale_count += 1
                    continue

                valid_values.append(float(state))

            except Exception as e:
                logger.error(f"Failed to fetch data for {eid}: {e}")

        # Construct statistics for monitoring/MQTT
        stats = {
            "stale_sensors": stale_count,
            "active_sensors": len(valid_values),
            "raw_values": valid_values,
            "mode": self.mode
        }

        # Calculate final value using the selected mode (min, mean, median)
        result = self._calculate_aggregation(valid_values)
        
        if result is None:
            stats["error"] = "No valid data (all sensors were stale or unavailable)"
            
        return result, stats