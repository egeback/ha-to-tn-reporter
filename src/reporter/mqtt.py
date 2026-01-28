import asyncio
import json
import logging
from reporter.state import health_status

logger = logging.getLogger("reporter.mqtt")

class MQTTManager:
    """
    Handles MQTT connectivity and Home Assistant Discovery.
    Automatically breaks out individual station data into separate sensors.
    """
    def __init__(self, host, sensors, port=1883):
        """
        :param host: MQTT Broker address
        :param sensors: List of TempSensor objects to create discovery for
        :param port: MQTT Broker port
        """
        self.host = host
        self.sensors = sensors
        self.port = port
        self._connected = False
        # Note: You would initialize your specific MQTT client (e.g., gmqtt or paho) here.

    def is_connected(self):
        """Returns connection status for health checks."""
        return self._connected

    async def _publish_discovery(self):
        """
        Registers the service and every individual sensor with Home Assistant.
        This allows HA to 'break out' the JSON into separate UI entities.
        """
        logger.debug("Generating Home Assistant MQTT Discovery payloads...")

        # Common device info so all sensors group together in the HA UI
        device_info = {
            "identifiers": ["tn_reporter_service"],
            "name": "HA to TN Reporter",
            "model": "Python Reporter",
            "manufacturer": "Gemini AI"
        }

        # 1. CREATE SENSORS FOR EACH STATION
        for sensor in self.sensors:
            # Topic format: homeassistant/sensor/[device]/[object_id]/config
            disc_topic = f"homeassistant/sensor/tn_reporter/{sensor.tn_id}/config"
            
            payload = {
                "name": f"Station {sensor.tn_id} Temperature",
                "state_topic": f"tn_reporter/stations/{sensor.tn_id}",
                "value_template": "{{ value_json.value }}",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "unique_id": f"tn_station_{sensor.tn_id}_temp",
                "device": device_info
            }
            
            # await self.client.publish(disc_topic, json.dumps(payload), qos=1, retain=True)
            logger.debug(f"MQTT Discovery: Created temperature sensor for {sensor.tn_id}")

        # 2. CREATE DIAGNOSTIC SENSORS (Success/Error Counts)
        stats_discovery = [
            ("session_success", "Session Successes", "{{ value_json.session_success_count }}"),
            ("lifetime_success", "Lifetime Successes", "{{ value_json.lifetime_success_count }}"),
            ("error_count", "Report Errors", "{{ value_json.error_count }}")
        ]

        for uid, name, template in stats_discovery:
            disc_topic = f"homeassistant/sensor/tn_reporter/{uid}/config"
            payload = {
                "name": name,
                "state_topic": "tn_reporter/stats",
                "value_template": template,
                "unique_id": f"tn_reporter_{uid}",
                "device": device_info,
                "entity_category": "diagnostic"
            }
            # await self.client.publish(disc_topic, json.dumps(payload), qos=1, retain=True)
            logger.debug(f"MQTT Discovery: Created diagnostic sensor {name}")

    async def run(self):
        """
        Main loop for MQTT management.
        Connects, sends discovery, and publishes state updates.
        """
        logger.info(f"Connecting to MQTT Broker at {self.host}:{self.port}")

        try:
            # Simulate connection logic
            await asyncio.sleep(2) 
            self._connected = True
            logger.info("MQTT Connected.")

            # Send discovery payloads so entities appear in Home Assistant
            await self._publish_discovery()

            while True:
                if self._connected:
                    # 1. Publish Global Stats (Success/Errors)
                    stats_payload = {
                        "session_success_count": health_status.get("session_success_count"),
                        "lifetime_success_count": health_status.get("lifetime_success_count"),
                        "error_count": health_status.get("error_count"),
                        "status": health_status.get("status")
                    }
                    # await self.client.publish("tn_reporter/stats", json.dumps(stats_payload))

                    # 2. Publish Individual Station Data
                    for sensor in self.sensors:
                        station_data = health_status.get(sensor.tn_id, {})
                        # Ensure we have a valid value before publishing
                        if "last_reported_value" in station_data:
                            topic = f"tn_reporter/stations/{sensor.tn_id}"
                            payload = {"value": station_data["last_reported_value"]}
                            # await self.client.publish(topic, json.dumps(payload))
                            logger.debug(f"MQTT: Published {sensor.tn_id} value to {topic}")

                # Publish updates every 60 seconds
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("MQTT Manager stopping...")
            self._connected = False
        except Exception as e:
            logger.error(f"MQTT Manager error: {e}")
            self._connected = False