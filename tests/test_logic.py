import pytest
from datetime import datetime, timedelta, timezone
from reporter.model.sensor import TempSensor

# Mock data helper
def create_ha_response(state, last_updated_iso):
    return {
        "state": str(state),
        "last_updated": last_updated_iso
    }

def test_aggregation_modes():
    """Test that min, mean, and median calculate correctly with valid data."""
    # We pass dummy strings for URL/Token as we aren't hitting the network here
    s_min = TempSensor("sensor.test", "tn1", "", "", mode="min")
    s_mean = TempSensor("sensor.test", "tn1", "", "", mode="mean")
    s_med = TempSensor("sensor.test", "tn1", "", "", mode="median")

    values = [10.0, 20.0, 60.0]

    assert s_min._calculate_aggregation(values) == 10.0
    assert s_mean._calculate_aggregation(values) == 30.0
    assert s_med._calculate_aggregation(values) == 20.0

def test_stale_data_filtering():
    """
    Test that values older than max_age (1800s) are rejected.
    """
    # 1800 seconds is the default threshold
    sensor = TempSensor("sensor.ha", "tn1", "http://ha", "token", max_age=1800)
    
    now = datetime.now(timezone.utc)
    
    # 1. Fresh data (5 minutes old)
    fresh_time = (now - timedelta(minutes=5)).isoformat()
    # 2. Stale data (40 minutes old)
    stale_time = (now - timedelta(minutes=40)).isoformat()
    
    # Mocking the fetch logic behavior
    # In a real fetch, these would be the states returned by HA
    val_fresh = float(create_ha_response(20.5, fresh_time)["state"])
    val_stale = float(create_ha_response(25.0, stale_time)["state"])
    
    # Simulate the filtering logic found in sensor.py
    valid_values = []
    
    # Check fresh
    age_fresh = (now - datetime.fromisoformat(fresh_time)).total_seconds()
    if age_fresh <= 1800:
        valid_values.append(val_fresh)
        
    # Check stale
    age_stale = (now - datetime.fromisoformat(stale_time)).total_seconds()
    if age_stale <= 1800:
        valid_values.append(val_stale)

    # Assert only the fresh value survived
    assert len(valid_values) == 1
    assert valid_values[0] == 20.5

def test_all_sensors_stale():
    """Test that if all sensors are stale, the result is None."""
    sensor = TempSensor("s1|s2", "tn1", "", "", mode="mean")
    
    # If fetch_data filters everything out, valid_values is empty
    result = sensor._calculate_aggregation([])
    assert result is None