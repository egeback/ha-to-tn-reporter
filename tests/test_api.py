import pytest
import respx
import httpx
from httpx import Response
from reporter.main import report_to_tn
from reporter.model.sensor import TempSensor
from reporter.state import health_status

@respx.mock
@pytest.mark.asyncio
async def test_report_to_tn_success():
    """
    Tests that a 200 OK with 'ok' body results in a success.
    Uses respx.get(url) with a base string match.
    """
    # Fix: respx now uses direct string matching or regex
    # We match the base URL of the temperatur.nu API
    respx.get("http://www.temperatur.nu/rapportera.php").mock(
        return_value=Response(200, text="ok (0.123s)")
    )
    
    sensor = TempSensor("sensor.temp", "mystation", "http://ha", "token")
    
    async with httpx.AsyncClient() as client:
        # Reset counts for clean test session
        health_status["session_success_count"] = 0
        success = await report_to_tn(client, sensor, 22.5, "myhash")
        
    assert success is True

@respx.mock
@pytest.mark.asyncio
async def test_report_to_tn_api_error():
    """
    Tests that the reporter handles an explicit 'error' response from the TN API.
    """
    respx.get("http://www.temperatur.nu/rapportera.php").mock(
        return_value=Response(200, text="error: invalid hash")
    )
    
    sensor = TempSensor("sensor.temp", "mystation", "http://ha", "token")
    
    async with httpx.AsyncClient() as client:
        success = await report_to_tn(client, sensor, 22.5, "wronghash")
        
    assert success is False

@respx.mock
@pytest.mark.asyncio
async def test_report_to_tn_http_failure():
    """
    Tests that the reporter handles a 500 Server Error (Network/API down).
    """
    respx.get("http://www.temperatur.nu/rapportera.php").mock(
        return_value=Response(500, text="Internal Server Error")
    )
    
    sensor = TempSensor("sensor.temp", "mystation", "http://ha", "token")
    
    async with httpx.AsyncClient() as client:
        success = await report_to_tn(client, sensor, 22.5, "myhash")
        
    # Should return False and log the error, but not crash
    assert success is False