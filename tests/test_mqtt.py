import pytest
import json
import asyncio
from unittest.mock import AsyncMock
from reporter.mqtt import MQTTManager
from reporter.model.sensor import TempSensor

@pytest.mark.asyncio
async def test_mqtt_discovery_payloads():
    """
    Verify that _publish_discovery generates the correct number of config messages
    and that the payloads follow Home Assistant standards.
    """
    # Setup
    sensors = [TempSensor("sensor.outside", "station_1", "http://ha", "token")]
    # Use a custom base topic to verify templating
    mgr = MQTTManager("localhost", sensors, base_topic="my_reporter")
    
    # Execute
    await mgr._publish_discovery()
    
    # Verification
    # We expect:
    # 1. Temperature sensor config
    # 2. Winning sensor config
    # 3. Main Status config
    # 4. 11 Diagnostic stats sensors (including last_updated)
    # Total = 14 messages
    assert mgr.queue.qsize() == 14
    
    # Helper to find a specific config by unique_id suffix
    items = []
    while not mgr.queue.empty():
        items.append(await mgr.queue.get())
        
    def get_payload(suffix):
        for prio, _seq, item in items:
            topic, payload_str, qos, retain = item
            payload = json.loads(payload_str)
            if payload["unique_id"].endswith(suffix):
                return topic, payload
        return None, None

    # 1. Check Temperature Sensor
    topic, payload = get_payload("_station_1_temp")
    assert topic == "homeassistant/sensor/tn_reporter/station_1_temperature/config"
    assert payload["name"] == "Station 1 Temperature"
    assert payload["state_topic"] == "my_reporter/state"
    assert "value_json.station['station_1'].temperature" in payload["value_template"]

    # 2. Check Winning Sensor
    topic, payload = get_payload("_station_1_winning_sensor")
    assert payload["name"] == "Station 1 Winning Sensor"
    assert "value_json.station['station_1'].sensor_name" in payload["value_template"]

    # 3. Check Last Updated Sensor
    topic, payload = get_payload("_station_1_last_updated")
    assert payload["name"] == "Station 1 Last Updated"
    assert "value_json.station['station_1'].last_updated" in payload["value_template"]

    # 4. Check a Stat Sensor (e.g., Uptime)
    topic, payload = get_payload("_uptime")
    assert payload["name"] == "Station 1 Reporter Uptime" # derived from device_name logic
    assert payload["device_class"] == "duration"

@pytest.mark.asyncio
async def test_mqtt_state_update_formatting():
    """
    Verify that put_update correctly formats the internal state dictionary
    into the MQTT JSON structure expected by the discovery payloads.
    """
    sensors = [TempSensor("sensor.outside", "station_1", "http://ha", "token")]
    mgr = MQTTManager("localhost", sensors, base_topic="my_reporter")
    client = AsyncMock()
    
    # Mock data coming from main.py
    input_data = {
        "stats": {
            "uptime_seconds": 12345,
            "status": "running"
        },
        "stations": {
            "station_1": {
                "last_reported_value": 21.5,
                "winning_sensor": "sensor.outside",
                "last_updated": "2023-01-01T12:00:00+00:00",
                "sensor_map": {"sensor.outside": 21.5},
                "total_sensors": 1,
                "stale_sensors": 0
            }
        }
    }
    
    # Queue the update
    mgr.put_update(input_data)
    
    # Process the queue (run consumer for one item)
    task = asyncio.create_task(mgr._consume_queue(client))
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
        
    # Verify publish was called
    assert client.publish.called
    call_args = client.publish.call_args
    payload_str = call_args[0][1]
    payload = json.loads(payload_str)
    
    # Check that "stations" (plural) was reformatted to "station" (singular)
    assert "station" in payload
    assert payload["station"]["station_1"]["temperature"] == 21.5
    assert payload["station"]["station_1"]["sensor_name"] == "sensor.outside"
    assert payload["station"]["station_1"]["last_updated"] == "2023-01-01T12:00:00+00:00"

def test_build_mqtt_payload_structure():
    """
    Unit test for the _build_mqtt_payload helper method.
    Ensures the internal state is correctly transformed into the public schema.
    """
    sensors = []
    mgr = MQTTManager("localhost", sensors)
    
    input_data = {
        "stats": {"status": "ok"},
        "stations": {
            "s1": {
                "winning_sensor": "w1",
                "last_reported_value": 10.0,
                "last_updated": "2023-01-01T12:00:00+00:00",
                "sensor_map": {"w1": 10.0},
                "total_sensors": 1,
                "stale_sensors": 0
            }
        }
    }
    
    result = mgr._build_mqtt_payload(input_data)
    
    assert result["stats"]["status"] == "ok"
    assert "station" in result
    assert "s1" in result["station"]
    assert result["station"]["s1"]["sensor_name"] == "w1"
    assert result["station"]["s1"]["temperature"] == 10.0
    assert result["station"]["s1"]["last_updated"] == "2023-01-01T12:00:00+00:00"
    assert result["station"]["s1"]["evaluated_count"] == 1
    assert result["station"]["s1"]["disqualified_count"] == 0