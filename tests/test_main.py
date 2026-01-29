import pytest
from unittest.mock import patch
from reporter.main import parse_sensors, main_loop
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

@pytest.mark.asyncio
async def test_mqtt_topic_arg_passed_to_manager():
    """
    Verify that the --mqtt-topic CLI argument is correctly parsed 
    and passed to the MQTTManager constructor.
    """
    # Mock arguments to satisfy the required checks in main_loop
    test_args = [
        "reporter.main",
        "--ha-url", "http://localhost:8123",
        "--ha-token", "fake_token",
        "--tn-hash", "fake_hash",
        "--mapping", "station=sensor.test",
        "--mqtt-host", "192.168.1.100",
        "--mqtt-topic", "custom/topic/root"
    ]

    # We mock MQTTManager to verify it was called with the right args
    # We mock start_health_server to raise an exception and break the infinite loop early
    with patch("sys.argv", test_args), \
         patch("reporter.main.MQTTManager") as MockMQTT, \
         patch("reporter.main.start_health_server", side_effect=RuntimeError("Break Loop")), \
         patch("reporter.main.parse_sensors", return_value=[]):
        
        try:
            await main_loop()
        except RuntimeError as e:
            assert str(e) == "Break Loop"

        # Verify MQTTManager was initialized with the custom topic
        MockMQTT.assert_called_once()
        call_kwargs = MockMQTT.call_args.kwargs
        assert call_kwargs["base_topic"] == "custom/topic/root"
        assert call_kwargs["host"] == "192.168.1.100"