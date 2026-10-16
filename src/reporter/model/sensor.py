import logging
import statistics
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger("reporter.sensor")

# Retry transient HA errors (502/503/504 and network/timeout). 404/4xx are
# treated as permanent (entity missing or unauthorized) and not retried.
_HA_RETRY_ATTEMPTS = 2
_HA_RETRY_BACKOFF = 3.0  # seconds between attempts


async def _fetch_one(client, url, headers):
    """GET one HA entity, retrying once on 5xx or network/timeout errors."""
    last_exc = None
    for attempt in range(1, _HA_RETRY_ATTEMPTS + 1):
        try:
            resp = await client.get(url, headers=headers, timeout=5.0)
            if 500 <= resp.status_code < 600 and attempt < _HA_RETRY_ATTEMPTS:
                logger.debug(f"HA {resp.status_code} for {url} (attempt {attempt}); retrying.")
                await asyncio.sleep(_HA_RETRY_BACKOFF)
                continue
            return resp
        except Exception as e:
            last_exc = e
            if attempt < _HA_RETRY_ATTEMPTS:
                logger.debug(f"HA fetch error for {url} (attempt {attempt}): {type(e).__name__}; retrying.")
                await asyncio.sleep(_HA_RETRY_BACKOFF)
                continue
            return e
    return last_exc


class TempSensor:
    """
    Represents a group of one or more Home Assistant sensors mapped to one Temperatur.nu ID.
    Handles data fetching, age-validation (stale data), and mathematical aggregation.

    Two layers of bad-value protection:
      * Sanity range: any value outside [temp_min, temp_max] is dropped — catches
        battery-dead / disconnected sensors that report absurd numbers.
      * Asymmetric outlier rejection: when at least `outlier_min_group` valid
        values are left, sensors more than `outlier_threshold_high` °C ABOVE the
        median or more than `outlier_threshold_low` °C BELOW the median are
        dropped. The asymmetry matters for `min` mode: a real shade sensor in a
        mostly-sunny group will read well below the median, and we must NOT drop
        it (that would force min() to report a sun reading). Defaults are 15 °C
        upper / 25 °C lower. Skipped for small groups where the median isn't
        robust.
    """
    def __init__(self, ha_ids, tn_id, ha_url, ha_token, mode="min", max_age=1800,
                 temp_min=-50.0, temp_max=60.0,
                 outlier_threshold_high=15.0, outlier_threshold_low=25.0,
                 outlier_min_group=3):
        self.ha_ids = ha_ids.split('|') # Supports pipe-separated IDs: "sensor.a|sensor.b"
        self.tn_id = tn_id
        self.ha_url = ha_url
        self.ha_token = ha_token
        self.mode = mode
        self.max_age = max_age # Default 30 minutes (1800 seconds)
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.outlier_threshold_high = outlier_threshold_high
        self.outlier_threshold_low = outlier_threshold_low
        self.outlier_min_group = outlier_min_group

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
        rejected_sanity = 0
        sensor_map = {}
        last_updated_map = {}
        headers = {"Authorization": f"Bearer {self.ha_token}"}

        # Create concurrent tasks for all sensors in the group
        tasks = [
            _fetch_one(client, f"{self.ha_url}/api/states/{eid}", headers)
            for eid in self.ha_ids
        ]

        # Wait for all requests to complete (or fail)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            eid = self.ha_ids[i]

            if isinstance(result, Exception):
                desc = f"{type(result).__name__}: {result}" if str(result) else type(result).__name__
                logger.error(f"Failed to fetch data for {eid}: {desc}")
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

                # Sanity range — drop physically-impossible readings before they
                # poison the aggregation. Battery-dead sensors often report 0 or
                # a wildly negative number.
                if val < self.temp_min or val > self.temp_max:
                    logger.warning(
                        f"Sensor {eid} dropped: value {val}°C outside sanity range "
                        f"[{self.temp_min}, {self.temp_max}]°C."
                    )
                    rejected_sanity += 1
                    continue

                valid_values.append(val)
                sensor_map[eid] = val
                last_updated_map[eid] = ts_str

            except Exception as e:
                logger.error(f"Failed to fetch data for {eid}: {e}")

        # Asymmetric outlier rejection — only meaningful with enough sensors for
        # the median to be robust. With <3 valid readings we have no good
        # reference, so we trust them and rely on sanity range alone.
        # Upper threshold is tighter than lower so a real shade sensor in a
        # mostly-sunny group survives (min mode depends on it).
        rejected_outlier = 0
        if len(valid_values) >= self.outlier_min_group:
            group_median = statistics.median(valid_values)
            survivors = []
            survivor_map = {}
            survivor_last_updated = {}
            for eid, v in sensor_map.items():
                deviation = v - group_median
                drop = (
                    (deviation > self.outlier_threshold_high)
                    or (-deviation > self.outlier_threshold_low)
                )
                if drop:
                    side = "above" if deviation > 0 else "below"
                    limit = self.outlier_threshold_high if deviation > 0 else self.outlier_threshold_low
                    logger.warning(
                        f"Sensor {eid} dropped: value {v}°C is {abs(deviation):.1f}°C "
                        f"{side} group median ({group_median}°C, {side}-threshold {limit}°C)."
                    )
                    rejected_outlier += 1
                    continue
                survivors.append(v)
                survivor_map[eid] = v
                survivor_last_updated[eid] = last_updated_map[eid]
            valid_values = survivors
            sensor_map = survivor_map
            last_updated_map = survivor_last_updated

        # Construct statistics for monitoring/MQTT
        stats = {
            "stale_sensors": stale_count,
            "rejected_sanity": rejected_sanity,
            "rejected_outlier": rejected_outlier,
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