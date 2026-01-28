import pytest
import respx
from httpx import Response, AsyncClient
from datetime import datetime, timezone, timedelta
from reporter.model.sensor import TempSensor

@pytest.mark.asyncio
@respx.mock
async def test_sensor_aggregation_min_logic():
    """Test that the 'min' mode correctly picks the lowest value among fresh sensors."""
    ha_url = "http://ha.local"
    sensor = TempSensor("sensor.1|sensor.2", "tn_1", ha_url, "fake_token", mode="min", max_age=1800)
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Mock HA Responses: 22.5 and 21.0
    respx.get(f"{ha_url}/api/states/sensor.1").mock(return_value=Response(200, json={
        "state": "22.5", "last_updated": now
    }))
    respx.get(f"{ha_url}/api/states/sensor.2").mock(return_value=Response(200, json={
        "state": "21.0", "last_updated": now
    }))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 21.0
    assert stats["active_sensors"] == 2
    assert stats["stale_sensors"] == 0
    assert 21.0 in stats["raw_values"]

@pytest.mark.asyncio
@respx.mock
async def test_sensor_stale_filtering():
    """Test that sensors older than max_age are excluded and stats are returned correctly."""
    ha_url = "http://ha.local"
    # Max age is 30 mins (1800s)
    sensor = TempSensor("sensor.old", "tn_1", ha_url, "token", max_age=1800)
    
    # Create a timestamp 40 minutes ago
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    
    respx.get(f"{ha_url}/api/states/sensor.old").mock(return_value=Response(200, json={
        "state": "20.0", "last_updated": stale_time
    }))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    # Result should be None because the only sensor was stale
    assert result is None
    # Verify the dictionary keys exist even on failure
    assert stats["stale_sensors"] == 1
    assert stats["active_sensors"] == 0
    assert stats["raw_values"] == []
    assert "error" in stats

@pytest.mark.asyncio
@respx.mock
async def test_sensor_partial_stale():
    """Test a mix of fresh and stale sensors."""
    ha_url = "http://ha.local"
    sensor = TempSensor("sensor.fresh|sensor.stale", "tn_1", ha_url, "token", mode="mean")
    
    fresh_time = datetime.now(timezone.utc).isoformat()
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    
    respx.get(f"{ha_url}/api/states/sensor.fresh").mock(return_value=Response(200, json={
        "state": "10.0", "last_updated": fresh_time
    }))
    respx.get(f"{ha_url}/api/states/sensor.stale").mock(return_value=Response(200, json={
        "state": "50.0", "last_updated": stale_time
    }))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    # Should only use the fresh 10.0 value
    assert result == 10.0
    assert stats["active_sensors"] == 1
    assert stats["stale_sensors"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_sensor_age_filtering_scenarios():
    """
    Test suite to verify different age-based scenarios:
    1. Fresh sensor (should pass)
    2. Stale sensor (should fail)
    3. Partial stale (one good, one bad - should return the good one)
    """
    ha_url = "http://ha.local"
    # Max age set to 30 minutes (1800 seconds)
    sensor = TempSensor("s1|s2", "test_id", ha_url, "token", mode="min", max_age=1800)
    
    # SETUP TIMESTAMPS
    now_utc = datetime.now(timezone.utc)
    fresh_time = (now_utc - timedelta(minutes=5)).isoformat()   # 5 mins ago (OK)
    stale_time = (now_utc - timedelta(minutes=31)).isoformat()  # 31 mins ago (STALE)

    # 1. Mock S1 as FRESH (10.0 degrees)
    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={
        "state": "10.0", "last_updated": fresh_time
    }))
    
    # 2. Mock S2 as STALE (5.0 degrees)
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={
        "state": "5.0", "last_updated": stale_time
    }))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    # ASSERTIONS
    # Even though S2 has a lower value (5.0), it's stale, so result should be 10.0
    assert result == 10.0
    assert stats["active_sensors"] == 1
    assert stats["stale_sensors"] == 1
    assert stats["raw_values"] == [10.0]

@pytest.mark.asyncio
@respx.mock
async def test_all_sensors_stale():
    """Verify that if all sensors are stale, the result is None."""
    ha_url = "http://ha.local"
    sensor = TempSensor("s_old", "test_id", ha_url, "token", max_age=600) # 10 min limit
    
    # 15 minutes ago
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    
    respx.get(f"{ha_url}/api/states/s_old").mock(return_value=Response(200, json={
        "state": "20.0", "last_updated": stale_ts
    }))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result is None
    assert stats["active_sensors"] == 0
    assert stats["stale_sensors"] == 1