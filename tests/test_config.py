import pytest
from reporter.config import parse_sensors
from reporter.model.sensor import TempSensor

def test_parse_sensors_clean():
    """Test parsing a correctly formatted mapping string."""
    mapping = "station1=sensor.a|sensor.b,station2=sensor.c"
    sensors = parse_sensors(mapping, "http://ha", "token")
    
    assert len(sensors) == 2
    assert sensors[0].tn_id == "station1"
    assert sensors[0].ha_ids == ["sensor.a", "sensor.b"]
    assert sensors[1].tn_id == "station2"

def test_parse_sensors_auto_correct():
    """Test that the parser removes the variable name if accidentally included."""
    # This simulates the common Docker/Env var configuration error
    mapping = "REPORTER_SENSOR_MAPPING=station1=sensor.a"
    sensors = parse_sensors(mapping, "http://ha", "token")
    
    assert len(sensors) == 1
    assert sensors[0].tn_id == "station1"
    assert sensors[0].ha_ids == ["sensor.a"]

def test_parse_sensors_empty():
    """Test parsing an empty or None string."""
    assert parse_sensors(None, "url", "token") == []
    assert parse_sensors("", "url", "token") == []