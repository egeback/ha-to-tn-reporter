import logging
import statistics
import asyncio
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
        sensor_map = {}
        last_updated_map = {}
        headers = {"Authorization": f"Bearer {self.ha_token}"}

        # Create concurrent tasks for all sensors in the group
        tasks = [
            client.get(f"{self.ha_url}/api/states/{eid}", headers=headers, timeout=5.0)
            for eid in self.ha_ids
        ]
        
        # Wait for all requests to complete (or fail)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            eid = self.ha_ids[i]
            
            if isinstance(result, Exception):
                logger.error(f"Failed to fetch data for {eid}: {result}")
                continue
            
            if result.status_code != 200:
                logger.error(f"HA returned {result.status_code} for {eid}")
                continue

            try:
                data = result.json()
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
    
                val = float(state)
                valid_values.append(val)
                sensor_map[eid] = val
                last_updated_map[eid] = ts_str
    
            except Exception as e:
                logger.error(f"Failed to fetch data for {eid}: {e}")

        # Construct statistics for monitoring/MQTT
        stats = {
            "stale_sensors": stale_count,
            "active_sensors": len(valid_values),
            "total_sensors": len(self.ha_ids),
            "raw_values": valid_values,
            "sensor_map": sensor_map,
            "mode": self.mode
        }

        # Calculate final value using the selected mode (min, mean, median)
        result = self._calculate_aggregation(valid_values)
        
        winning_sensor = "N/A"
        winning_last_updated = None
        if result is not None:
            if self.mode == "min":
                # Find the first sensor that matches the result (which is the min value)
                for eid, val in sensor_map.items():
                    if val == result:
                        winning_sensor = eid
                        break
            elif self.mode == "median":
                # The median might be an average of two values, so it might not be in the original list.
                # Only identify a winner if the median is one of the actual sensor values.
                if result in valid_values:
                    for eid, val in sensor_map.items():
                        if val == result:
                            winning_sensor = eid
                            break
            
            # Determine last_updated for the result
            if winning_sensor != "N/A":
                winning_last_updated = last_updated_map.get(winning_sensor)
            else:
                # If no single winner (e.g. mean or interpolated median), use the most recent timestamp
                valid_timestamps = [last_updated_map[eid] for eid in sensor_map]
                if valid_timestamps:
                    winning_last_updated = max(valid_timestamps)

        stats["winning_sensor"] = winning_sensor
        stats["last_updated"] = winning_last_updated

        if result is None:
            stats["error"] = "No valid data (all sensors were stale or unavailable)"
            
        return result, stats