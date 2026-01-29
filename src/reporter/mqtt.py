import asyncio
import json
import logging
import aiomqtt
from aiomqtt import MqttError
from . import __version__

# Setup a dedicated logger for the MQTT module
logger = logging.getLogger("reporter.mqtt")

DISCOVERY_ROOT = "tn_reporter"

class MQTTManager:
    """
    Manages MQTT lifecycle using an internal asyncio.Queue.
    
    This architecture decouples the 'Producer' (the main reporting loop) from 
    the 'Consumer' (the MQTT network client). If the network is down, updates 
    buffer in the queue until the connection is restored.
    """
    
    def __init__(self, host, sensors, port=1883, username=None, password=None, base_topic="tn_reporter"):
        """
        Initializes the MQTT Manager.
        
        :param host: Broker hostname or IP address.
        :param sensors: List of TempSensor objects for HA discovery.
        :param port: Broker port (int).
        :param username: Authentication username (optional).
        :param password: Authentication password (optional).
        :param base_topic: Base MQTT topic for state and discovery (default: tn_reporter).
        """
        self.host = host
        self.sensors = sensors
        self.port = int(port) if port else 1883
        self.username = username
        self.password = password
        self.base_topic = base_topic
        
        # Internal state
        self._connected = False
        self.state_topic = f"{self.base_topic}/state"
        self.bridge_state_topic = f"{self.base_topic}/bridge/state"
        
        # Define command priorities for the queue
        self._PRIO_DISCOVERY = 0
        self._PRIO_STATE = 1
        
        # THE QUEUE: 
        # A PriorityQueue ensures discovery messages are always sent before state updates.
        self.queue = asyncio.PriorityQueue()

    def is_connected(self) -> bool:
        """Returns True if the MQTT client is currently connected."""
        return self._connected

    def put_update(self, data: dict):
        """
        The 'Producer' method. Call this from main.py to queue a new state update.
        
        :param data: A dictionary containing the current health_status.
        """
        # We use put_nowait because the main loop shouldn't block 
        # if the MQTT queue is busy.
        self.queue.put_nowait((self._PRIO_STATE, data))
        logger.debug(f"State update added to queue. Current queue size: {self.queue.qsize()}")

    async def _publish_discovery(self):
        """
        Queues Home Assistant MQTT Discovery payloads.
        Informed by the sensors list provided during initialization.
        """
        logger.info("Queueing Home Assistant Discovery payloads...")
        
        # Determine a descriptive name for the device. If only one station is
        # configured, use its name. Otherwise, use a generic name.
        if len(self.sensors) == 1:
            device_name = f"{self.sensors[0].tn_id.replace('_', ' ').title()} Reporter"
        else:
            device_name = "HA to TN Reporter"

        device = {
            "identifiers": [f"{self.base_topic}_service"],
            "name": device_name,
            "model": "Python Reporter",
            "sw_version": __version__
        }

        # Common availability settings for all entities from this reporter
        availability_config = {
            "availability_topic": self.bridge_state_topic,
            "payload_available": "online",
            "payload_not_available": "offline"
        }

        # 1. Create individual temperature sensors for each station
        for sensor in self.sensors:
            station_id = sensor.tn_id
            temp_topic = f"homeassistant/sensor/{DISCOVERY_ROOT}/{station_id}_temperature/config"
            temp_payload = {
                "name": f"{station_id.replace('_', ' ').title()} Temperature",
                "state_topic": self.state_topic,
                "value_template": f"{{{{ value_json.station['{station_id}'].temperature | default('unknown') }}}}",
                "unique_id": f"{self.base_topic}_{station_id}_temp",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "device": device,
                # Expose this station's detailed data as attributes
                "json_attributes_topic": self.state_topic,
                "json_attributes_template": f"{{{{ value_json.station['{station_id}'] | tojson }}}}",
                **availability_config
            }
            pub_tuple = (temp_topic, json.dumps(temp_payload), 1, True)
            self.queue.put_nowait((self._PRIO_DISCOVERY, pub_tuple))

            # Create a sensor for the winning sensor
            winning_sensor_topic = f"homeassistant/sensor/{DISCOVERY_ROOT}/{station_id}_winning_sensor/config"
            winning_sensor_payload = {
                "name": f"{station_id.replace('_', ' ').title()} Winning Sensor",
                "state_topic": self.state_topic,
                "value_template": f"{{{{ value_json.station['{station_id}'].sensor_name | default('N/A') }}}}",
                "unique_id": f"{self.base_topic}_{station_id}_winning_sensor",
                "device": device,
                "entity_category": "diagnostic",
                **availability_config
            }
            pub_tuple = (winning_sensor_topic, json.dumps(winning_sensor_payload), 1, True)
            self.queue.put_nowait((self._PRIO_DISCOVERY, pub_tuple))




        # 2. Create a single diagnostic sensor for overall status and stats
        diag_name = f"{device_name} Status"

        diag_topic = f"homeassistant/sensor/{DISCOVERY_ROOT}/status/config"
        diag_payload = {
            "name": diag_name,
            "state_topic": self.state_topic,
            "value_template": "{{ value_json.stats.status }}",
            "unique_id": f"{self.base_topic}_status",
            "device": device,
            "entity_category": "diagnostic",
            "icon": "mdi:cloud-upload-outline",
            # Expose the global stats as attributes
            "json_attributes_topic": self.state_topic,
            "json_attributes_template": "{{ value_json.stats | tojson }}",
            **availability_config
        }
        # Queue the publication command with high priority
        pub_tuple = (diag_topic, json.dumps(diag_payload), 1, True)
        self.queue.put_nowait((self._PRIO_DISCOVERY, pub_tuple))

        # 3. Create individual diagnostic sensors for statistics
        stats_sensors = [
            {"id": "uptime", "name": "Uptime", "key": "uptime_seconds", "cls": "duration", "unit": "s", "icon": "mdi:clock-outline", "sc": None},
            {"id": "session_start", "name": "Session Start", "key": "session_start_time_iso", "cls": "timestamp", "unit": None, "icon": None, "sc": None},
            {"id": "last_report", "name": "Last Successful Report", "key": "last_successful_report", "cls": "timestamp", "unit": None, "icon": None, "sc": None},
            {"id": "session_success", "name": "Session Success", "key": "session_success", "cls": None, "unit": None, "icon": "mdi:check-circle-outline", "sc": "total_increasing"},
            {"id": "lifetime_success", "name": "Lifetime Success", "key": "lifetime_success", "cls": None, "unit": None, "icon": "mdi:check-circle", "sc": "total_increasing"},
            {"id": "session_errors", "name": "Session Errors", "key": "session_errors", "cls": None, "unit": None, "icon": "mdi:alert-circle-outline", "sc": "total_increasing"},
            {"id": "lifetime_errors", "name": "Lifetime Errors", "key": "lifetime_errors", "cls": None, "unit": None, "icon": "mdi:alert-circle", "sc": "total_increasing"},
        ]

        for s in stats_sensors:
            topic = f"homeassistant/sensor/{DISCOVERY_ROOT}/{s['id']}/config"
            payload = {
                "name": f"{device_name} {s['name']}",
                "state_topic": self.state_topic,
                "value_template": f"{{{{ value_json.stats.{s['key']} }}}}",
                "unique_id": f"{self.base_topic}_{s['id']}",
                "device": device,
                "entity_category": "diagnostic",
                **availability_config
            }
            if s['cls']:
                payload["device_class"] = s['cls']
            if s['unit']:
                payload["unit_of_measurement"] = s['unit']
            if s['icon']:
                payload["icon"] = s['icon']
            if s['sc']:
                payload["state_class"] = s['sc']
            
            pub_tuple = (topic, json.dumps(payload), 1, True)
            self.queue.put_nowait((self._PRIO_DISCOVERY, pub_tuple))

    async def _consume_queue(self, client):
        """
        The 'Consumer' loop. Watches the queue and publishes items to the broker.
        """
        logger.info("MQTT Queue Consumer started.")
        while True:
            # Wait for the next item. PriorityQueue gives us a (priority, item) tuple.
            priority, item = await self.queue.get()
            
            try:
                # TYPE 1: A direct publication tuple (topic, payload, qos, retain)
                if isinstance(item, tuple):
                    topic, payload, qos, retain = item
                    await client.publish(topic, payload, qos=qos, retain=retain)
                    logger.debug(f"MQTT: Published direct command to topic '{topic}'")

                # TYPE 2: A state update dictionary
                elif isinstance(item, dict):
                    # This 'item' is now a pre-structured dictionary from main.py
                    # with 'stats' and 'stations' keys.
                    data_source = item
                    
                    payload_stats = data_source.get("stats", {})
                    stations_data = data_source.get("stations", {})

                    # Reformat the station data for the final MQTT payload
                    payload_stations = {}
                    for station_id, sensor_data in stations_data.items():
                        payload_stations[station_id] = {
                            "sensor_name": sensor_data.get("winning_sensor", "N/A"),
                            "temperature": sensor_data.get("last_reported_value"),
                            "raw_values": sensor_data.get("sensor_map", {}),
                            "evaluated_count": sensor_data.get("total_sensors", 0),
                            "disqualified_count": sensor_data.get("stale_sensors", 0)
                        }

                    # Combine into the final payload
                    payload = {
                        "stats": payload_stats,
                        "station": payload_stations
                    }

                    # Publish to the single unified topic
                    await client.publish(self.state_topic, json.dumps(payload), qos=1)
                    logger.info(f"MQTT: State published successfully. (Queue depth: {self.queue.qsize()})")
                
            except Exception as e:
                logger.error(f"Error publishing queued MQTT item: {e}")
            finally:
                # Mark the task as finished
                self.queue.task_done()

    async def run(self):
        """
        The main background task. Handles connection logic and triggers the consumer.
        This loop will endlessly try to connect and run the consumer. If a
        connection is lost, it will clean up and attempt to reconnect.
        """
        reconnect_interval = 5
        consumer_task = None
        
        # Define the Last Will and Testament (LWT) message
        will = aiomqtt.Will(
            topic=self.bridge_state_topic,
            payload="offline",
            qos=1,
            retain=True
        )

        while True:
            try:
                logger.info(f"Connecting to MQTT Broker @ {self.host}:{self.port}...")
                
                # Using the client's context manager handles connection and disconnection
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=10.0,
                    will=will
                ) as client:
                    self._connected = True
                    logger.info("MQTT Connection established.")

                    # Announce that the bridge is online
                    await client.publish(self.bridge_state_topic, "online", qos=1, retain=True)
                    logger.info(f"MQTT bridge state set to 'online' on topic '{self.bridge_state_topic}'")

                    # Queue Home Assistant discovery payloads on every successful connection
                    await self._publish_discovery()

                    # Start the queue consumer task in the background
                    consumer_task = asyncio.create_task(self._consume_queue(client))
                    
                    # Wait until the client signals disconnection
                    await client._disconnected

            except MqttError as e:
                # This block is triggered by connection failures (e.g., wrong address, auth)
                # or if the connection is lost during operation.
                if any(x in str(e).lower() for x in ["not authorized", "bad username"]):
                    logger.critical(f"MQTT Authentication Failed: {e}. Stopping MQTT task.")
                    return # Stop the entire run() loop on auth failure
                
                logger.error(f"MQTT Connection error: {e}.")

            except Exception as e:
                logger.exception(f"An unexpected error occurred in the MQTT manager: {e}")

            finally:
                # This 'finally' block runs after every attempt, whether it succeeded or failed.
                self._connected = False
                if consumer_task and not consumer_task.done():
                    consumer_task.cancel()
                    try:
                        await consumer_task # Wait for the cancellation to complete
                    except asyncio.CancelledError:
                        pass # Expected behavior
                
                logger.info(f"MQTT client disconnected. Retrying in {reconnect_interval}s...")
                await asyncio.sleep(reconnect_interval)