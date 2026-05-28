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

@pytest.mark.asyncio
@respx.mock
async def test_winning_sensor_min():
    """Test that the correct sensor ID is identified as the 'winner' in min mode."""
    ha_url = "http://ha.local"
    # s2 will be the lowest (18.0)
    sensor = TempSensor("s1|s2|s3", "tn_id", ha_url, "token", mode="min")
    
    now = datetime.now(timezone.utc).isoformat()
    
    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "20.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "18.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s3").mock(return_value=Response(200, json={"state": "22.0", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 18.0
    assert stats["winning_sensor"] == "s2"

@pytest.mark.asyncio
@respx.mock
async def test_winning_sensor_median_odd():
    """Test median mode with an odd number of values (exact match)."""
    ha_url = "http://ha.local"
    # Values: 10, 20, 30 -> Median is 20 (s2)
    sensor = TempSensor("s1|s2|s3", "tn_id", ha_url, "token", mode="median")
    
    now = datetime.now(timezone.utc).isoformat()
    
    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "10.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "20.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s3").mock(return_value=Response(200, json={"state": "30.0", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 20.0
    assert stats["winning_sensor"] == "s2"

@pytest.mark.asyncio
@respx.mock
async def test_winning_sensor_median_even():
    """Test median mode with even number of values (interpolated)."""
    ha_url = "http://ha.local"
    # Values: 10, 20, 30, 40 -> Median is 25. No sensor has 25.
    sensor = TempSensor("s1|s2|s3|s4", "tn_id", ha_url, "token", mode="median")
    
    now = datetime.now(timezone.utc).isoformat()
    
    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "10.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "20.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s3").mock(return_value=Response(200, json={"state": "30.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s4").mock(return_value=Response(200, json={"state": "40.0", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 25.0
    # Since 25.0 is an average of 20 and 30, no single sensor "won"
    assert stats["winning_sensor"] == "N/A"

@pytest.mark.asyncio
@respx.mock
async def test_api_error_resilience():
    """Test that a 500 error from one sensor doesn't crash the group."""
    ha_url = "http://ha.local"
    sensor = TempSensor("s_good|s_bad", "tn_id", ha_url, "token", mode="min")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # s_good returns valid data
    respx.get(f"{ha_url}/api/states/s_good").mock(return_value=Response(200, json={"state": "15.0", "last_updated": now}))
    # s_bad returns Internal Server Error
    respx.get(f"{ha_url}/api/states/s_bad").mock(return_value=Response(500))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    # Should ignore the error and use the valid data
    assert result == 15.0
    assert stats["active_sensors"] == 1
    assert stats["total_sensors"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_sanity_range_drops_absurd_values():
    """Sensors reporting values outside [temp_min, temp_max] must be dropped."""
    ha_url = "http://ha.local"
    sensor = TempSensor(
        "s_ok|s_low|s_high", "tn_id", ha_url, "token",
        mode="min", temp_min=-50.0, temp_max=60.0,
    )
    now = datetime.now(timezone.utc).isoformat()

    respx.get(f"{ha_url}/api/states/s_ok").mock(return_value=Response(200, json={"state": "15.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s_low").mock(return_value=Response(200, json={"state": "-99.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s_high").mock(return_value=Response(200, json={"state": "120.0", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 15.0
    assert stats["active_sensors"] == 1
    assert stats["rejected_sanity"] == 2
    assert stats["rejected_outlier"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_outlier_rejection_drops_broken_sensor_in_group():
    """The sensor 2 -25.5°C scenario: one sensor far below the rest is dropped."""
    ha_url = "http://ha.local"
    sensor = TempSensor(
        "s1|s2|s3|s4", "tn_id", ha_url, "token",
        mode="min", outlier_threshold_high=15.0, outlier_threshold_low=25.0, outlier_min_group=3,
    )
    now = datetime.now(timezone.utc).isoformat()

    # Three sensors agree around 15-17°C; one reports -25.5°C and should be dropped.
    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "15.5", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "-25.5", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s3").mock(return_value=Response(200, json={"state": "16.8", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s4").mock(return_value=Response(200, json={"state": "17.5", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    # min of the survivors {15.5, 16.8, 17.5} is 15.5; -25.5 must be excluded.
    assert result == 15.5
    assert stats["active_sensors"] == 3
    assert stats["rejected_outlier"] == 1
    assert "s2" not in stats["sensor_map"]


@pytest.mark.asyncio
@respx.mock
async def test_outlier_check_skipped_for_small_group():
    """With <3 sensors the median is not robust — both values must be kept."""
    ha_url = "http://ha.local"
    sensor = TempSensor(
        "s1|s2", "tn_id", ha_url, "token",
        mode="min", outlier_threshold_high=15.0, outlier_threshold_low=25.0, outlier_min_group=3,
    )
    now = datetime.now(timezone.utc).isoformat()

    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "15.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "-10.0", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == -10.0
    assert stats["active_sensors"] == 2
    assert stats["rejected_outlier"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_normal_spread_within_threshold_is_kept():
    """Realistic sun/shade spread (~8°C) must NOT trip the outlier filter."""
    ha_url = "http://ha.local"
    sensor = TempSensor(
        "s1|s2|s3", "tn_id", ha_url, "token",
        mode="min", outlier_threshold_high=15.0, outlier_threshold_low=25.0, outlier_min_group=3,
    )
    now = datetime.now(timezone.utc).isoformat()

    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "18.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "22.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s3").mock(return_value=Response(200, json={"state": "26.0", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 18.0
    assert stats["active_sensors"] == 3
    assert stats["rejected_outlier"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_shade_sensor_survives_sun_majority():
    """Edge case for min-mode: most sensors in direct sun, one in shade. The
    shade sensor reads ~17°C below the sunny median but MUST be kept so min()
    can correctly report the shade temperature. This is exactly the scenario
    that defeats a symmetric outlier filter."""
    ha_url = "http://ha.local"
    sensor = TempSensor(
        "sun1|sun2|sun3|sun4|sun5|shade", "tn_id", ha_url, "token",
        mode="min", outlier_threshold_high=15.0, outlier_threshold_low=25.0, outlier_min_group=3,
    )
    now = datetime.now(timezone.utc).isoformat()

    # Five sun-exposed sensors all reading ~35°C; one shaded sensor at 18°C.
    for i in range(1, 6):
        respx.get(f"{ha_url}/api/states/sun{i}").mock(
            return_value=Response(200, json={"state": "35.0", "last_updated": now})
        )
    respx.get(f"{ha_url}/api/states/shade").mock(
        return_value=Response(200, json={"state": "18.0", "last_updated": now})
    )

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    # Shade sensor must survive (within the 25°C low-side budget) so min() picks it.
    assert result == 18.0
    assert stats["active_sensors"] == 6
    assert stats["rejected_outlier"] == 0
    assert "shade" in stats["sensor_map"]


@pytest.mark.asyncio
@respx.mock
async def test_stuck_low_sensor_still_dropped_with_asymmetric_threshold():
    """The sensor 2 (-25.5°C) scenario must still be caught — its 40°C+
    deviation exceeds even the generous 25°C low-side threshold."""
    ha_url = "http://ha.local"
    sensor = TempSensor(
        "s1|s2|s3|s_broken", "tn_id", ha_url, "token",
        mode="min", outlier_threshold_high=15.0, outlier_threshold_low=25.0, outlier_min_group=3,
    )
    now = datetime.now(timezone.utc).isoformat()

    respx.get(f"{ha_url}/api/states/s1").mock(return_value=Response(200, json={"state": "15.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s2").mock(return_value=Response(200, json={"state": "16.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s3").mock(return_value=Response(200, json={"state": "17.0", "last_updated": now}))
    respx.get(f"{ha_url}/api/states/s_broken").mock(return_value=Response(200, json={"state": "-25.5", "last_updated": now}))

    async with AsyncClient() as client:
        result, stats = await sensor.fetch_data(client)

    assert result == 15.0
    assert stats["rejected_outlier"] == 1
    assert "s_broken" not in stats["sensor_map"]