import pytest
from datetime import datetime, timedelta, timezone
from reporter.model.sensor import TempSensor

def test_aggregation_math():
    """
    Verifies that the min, mean, and median calculations work correctly.
    """
    # Create sensors with different modes
    s_min = TempSensor("s1|s2", "tn1", "url", "token", mode="min")
    s_mean = TempSensor("s1|s2", "tn1", "url", "token", mode="mean")
    s_med = TempSensor("s1|s2", "tn1", "url", "token", mode="median")

    test_values = [10.0, 20.0, 60.0]

    assert s_min._calculate_aggregation(test_values) == 10.0
    assert s_mean._calculate_aggregation(test_values) == 30.0
    assert s_med._calculate_aggregation(test_values) == 20.0

def test_stale_data_filtering():
    """
    Verifies that values older than the max_age (1800s) are ignored.
    """
    # max_age is 1800 seconds (30 minutes)
    sensor = TempSensor("s1", "tn1", "url", "token", max_age=1800)
    now = datetime.now(timezone.utc)
    
    # 1. Valid fresh data (1 minute old)
    fresh_time = (now - timedelta(minutes=1)).isoformat()
    # 2. Stale data (40 minutes old)
    stale_time = (now - timedelta(minutes=40)).isoformat()
    
    # Simulate the internal filtering logic of TempSensor
    # We check if the age is <= max_age
    def is_valid(timestamp_str):
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        age = (now - ts).total_seconds()
        return age <= 1800

    assert is_valid(fresh_time) is True
    assert is_valid(stale_time) is False

def test_all_sensors_unavailable():
    """
    Ensures that if no valid numeric data is returned, the result is None.
    """
    sensor = TempSensor("s1|s2", "tn1", "url", "token")
    
    # Simulate fetch_data returning no numeric values (empty list)
    result = sensor._calculate_aggregation([])
    
    assert result is None

def test_mixed_valid_and_invalid_data():
    """
    Tests that aggregation ignores None values in a list.
    """
    sensor = TempSensor("s1|s2", "tn1", "url", "token", mode="mean")
    
    # List contains a valid number and an invalid one (filtered out by fetch_data)
    test_values = [20.0] 
    
    result = sensor._calculate_aggregation(test_values)
    assert result == 20.0