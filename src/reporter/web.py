import logging
import time
from aiohttp import web
from reporter.state import health_status

# Initialize the logger for the web module
logger = logging.getLogger("reporter.web")

async def start_health_server(mqtt_manager, port=8080):
    """
    Initializes and starts the asynchronous HTTP health server.
    
    This server provides a /health endpoint used for:
    1. Docker HEALTHCHECK instructions.
    2. Real-time debugging of sensor counts.
    3. Verifying the MQTT connection status.

    :param mqtt_manager: The instance of MQTTManager to query for connection status.
    :param port: The TCP port to listen on (default: 8080).
    """
    app = web.Application()

    async def health_handler(request):
        """
        HTTP Handler for the /health endpoint.
        
        Logic:
        - Updates the 'mqtt_connected' status in the global state.
        - Checks if the reporter is in a 'running' state.
        - Returns 200 OK if healthy, 503 Service Unavailable if degraded.
        """
        logger.debug("Health check requested via Web API.")

        # Sync the real-time connection status from the MQTT manager into our state object
        health_status["mqtt_connected"] = mqtt_manager.is_connected()

        # Define health criteria:
        # 1. Must not be in the 'starting' phase.
        # 2. MQTT must be actively connected (optional, but recommended for full integration).
        is_healthy = (
            health_status["status"] != "starting" and 
            health_status["mqtt_connected"] is True
        )

        # Calculate uptime for the response
        uptime_seconds = int(time.time() - health_status["session_start_time"])

        # Prepare the JSON payload
        # This includes both the general status and the broken-out metrics
        response_data = {
            "status": health_status["status"],
            "mqtt_connected": health_status["mqtt_connected"],
            "uptime_seconds": uptime_seconds,
            "version": health_status.get("version", "1.0.0"),
            "counters": {
                "session_success": health_status["session_success_count"],
                "lifetime_success": health_status["lifetime_success_count"],
                "errors": health_status["error_count"]
            },
            "last_ha_fetch": health_status["last_ha_fetch"]
        }

        # Return 200 if healthy, 503 if there is an issue (e.g., MQTT disconnected)
        return web.json_response(
            data=response_data, 
            status=200 if is_healthy else 503
        )

    # Register the route
    app.router.add_get('/health', health_handler)

    # Set up the runner and the TCPSite
    # Using '0.0.0.0' allows the server to be reached from outside a Docker container
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    try:
        await site.start()
        logger.info(f"Web Health Server is live at http://0.0.0.0:{port}/health")
    except Exception as e:
        logger.error(f"Failed to start Web Health Server: {e}")

# This module is typically called by main.py using:
# await start_health_server(mqtt_instance, port=8080)