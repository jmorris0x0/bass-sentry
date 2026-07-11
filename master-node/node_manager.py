import json
import logging
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from correlation import DataHandler

logger = logging.getLogger(__name__)


class DataManager:
    def __init__(
        self,
        influx_url,
        influx_token,
        influx_bucket,
        influx_org,
        mqtt_host=None,
        mqtt_port=None,
        transport_config=None,
    ):
        """
        Initialize DataManager.

        Args:
            influx_url: InfluxDB URL
            influx_token: InfluxDB token
            influx_bucket: InfluxDB bucket
            influx_org: InfluxDB org
            mqtt_host: MQTT broker host (legacy, for backward compatibility)
            mqtt_port: MQTT broker port (legacy, for backward compatibility)
            transport_config: Transport configuration dict (if provided, overrides MQTT)
        """
        self.influx_bucket = influx_bucket
        self.influx_org = influx_org
        self.influx_client = self._connect_to_influx(
            influx_url, influx_token, influx_bucket, influx_org
        )
        self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
        self.write_api.errors_callback = self.write_errors_callback

        # Use pluggable transport if config provided, otherwise legacy MQTT
        self.use_transport = transport_config is not None
        if self.use_transport:
            logger.info(
                f"Using pluggable transport: {transport_config.get('type', 'unknown')}"
            )
            self.transport = self._create_transport(transport_config)
            self.mqtt_client = None
        else:
            logger.info("Using legacy MQTT")
            self.mqtt_client = self._connect_to_mqtt(mqtt_host, mqtt_port)
            self.transport = None

        self.healthy_nodes = set()
        self.last_health_check = {}
        self.lock = threading.Lock()
        self.connected_nodes = set()
        self.subscribed_topics = set()
        self.data_handler = DataHandler()

    def _create_transport(self, config_dict):
        """Create transport from configuration dictionary."""
        try:
            # Add parent directory to path for common imports
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

            from common.transport import TransportConfig, get_transport

            config = TransportConfig.from_dict(config_dict)
            return get_transport(config)
        except ImportError as e:
            logger.error(f"Failed to import transport module: {e}")
            logger.error("Transport layer requires 'common' module to be accessible")
            logger.error(
                "For Docker deployments, ensure 'common/' is mounted or copied into container"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to create transport: {e}")
            raise

    def start(self):
        if not self.influx_client:
            logger.error("Could not connect to InfluxDB. Exiting...")
            sys.exit(1)

        if self.use_transport:
            # Connect transport
            if not self.transport.connect():
                logger.error("Failed to connect transport. Exiting...")
                sys.exit(1)

            # Subscribe to all topics
            self.transport.subscribe("#", self._transport_callback)
        else:
            # Legacy MQTT
            self.mqtt_client.on_message = (
                lambda client, userdata, message: self.on_message(
                    client, userdata, message
                )
            )
            self.mqtt_loop_start()

        threading.Thread(target=self.check_unhealthy_nodes, daemon=True).start()

        if not self.use_transport:
            # Only needed for MQTT (transport handles subscriptions automatically)
            threading.Thread(
                target=self.subscribe_to_topics_periodically, daemon=True
            ).start()

        logger.info("Master node started successfully.")
        logger.info("Press Ctrl+C to exit...")

    def _transport_callback(self, topic, data):
        """Callback for transport layer messages."""
        try:
            # If data is already a dict, use it directly; otherwise parse JSON
            payload = data if isinstance(data, dict) else json.loads(data)

            # Handle different message types
            msg_type = payload.get("type")
            if msg_type == "heartbeat":
                self.handle_heartbeat(payload)
            elif "status" in payload:
                self.handle_connection_status(payload)
            elif "health_check" in payload:
                self.handle_health_check(payload)
            else:
                self.handle_data_point(topic, payload)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to decode JSON from payload: {e}")

    def subscribe_to_topics_periodically(self):  # Corrected
        while True:
            self.subscribe_to_topics()
            time.sleep(10)

    def _connect_to_influx(self, url, token, bucket, org):
        logger.info(f"Attempting to connect to InfluxDB with URL: {url}")
        try:
            client = InfluxDBClient(url=url, token=token, database=bucket, org=org)
            logger.info("Successfully connected to InfluxDB!")
        except Exception as e:
            logger.error(f"Error connecting to InfluxDB: {e}")
            return None
        return client

    def _connect_to_mqtt(self, host, port):
        logger.info("Connecting to MQTT broker...")
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self.on_connect
        client.connect(host, port, 60)
        return client

    def on_connect(self, client, userdata, flags, reason_code, properties):
        logger.info(f"Connected to MQTT broker with result code {reason_code}")
        self.subscribe_to_topics()

    def get_all_topics(self):
        # Use wildcard '#' to subscribe to all topics
        return ["#"]

    def on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))

            # Handle different message types
            msg_type = payload.get("type")
            if msg_type == "heartbeat":
                self.handle_heartbeat(payload)
            elif "status" in payload:
                self.handle_connection_status(payload)
            elif "health_check" in payload:
                self.handle_health_check(payload)
            else:
                self.handle_data_point(message.topic, payload)
        except (json.JSONDecodeError, ValueError):
            logger.error(
                f"Failed to decode JSON from payload: {message.payload.decode('utf-8')}"
            )

    def mqtt_loop_start(self):
        self.mqtt_client.loop_start()

    def mqtt_loop_stop(self):
        """Stop MQTT or transport connection."""
        if self.use_transport:
            if self.transport:
                self.transport.disconnect()
        else:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()

    def subscribe_to_topics(self):
        topics = self.get_all_topics()
        logger.debug(f"Subscribing to topics: {topics}")
        for topic in topics:
            if topic not in self.subscribed_topics:
                self.mqtt_client.subscribe(topic)
                logger.info(f"Subscribed to topic: {topic}")
                self.subscribed_topics.add(topic)

    def handle_health_check(self, payload):
        with self.lock:
            node_name = payload[
                "node_name"
            ]  # Assuming the payload is a dictionary with a "node_name" key
            if node_name not in self.healthy_nodes:
                logger.info(f"Discovered new node: {node_name}")
            self.healthy_nodes.add(node_name)
            self.connected_nodes.add(node_name)  # Also add to connected nodes
            self.last_health_check[node_name] = time.time()
            logger.debug(f"Current connected nodes: {self.connected_nodes}")

    def handle_heartbeat(self, payload):
        """Handle heartbeat messages from remote nodes.

        Heartbeat format:
        {
            "type": "heartbeat",
            "node_name": "aa:bb:cc:dd:ee:ff",
            "timestamp": 1234567890.123,
            "status": "connected",
            "stats": {
                "messages_sent": 100,
                "messages_failed": 2,
                "buffer_size": 0,
                "heartbeats_sent": 50
            }
        }
        """
        with self.lock:
            node_name = payload.get("node_name")
            if node_name is None:
                logger.warning("Heartbeat missing node_name")
                return

            # Update node tracking
            if node_name not in self.healthy_nodes:
                logger.info(f"Discovered new node via heartbeat: {node_name}")
            self.healthy_nodes.add(node_name)
            self.connected_nodes.add(node_name)
            self.last_health_check[node_name] = time.time()

            # Log stats if present (debug level to avoid spam)
            stats = payload.get("stats", {})
            if stats:
                logger.debug(
                    f"Heartbeat from {node_name}: "
                    f"sent={stats.get('messages_sent', 'N/A')}, "
                    f"failed={stats.get('messages_failed', 'N/A')}, "
                    f"buffer={stats.get('buffer_size', 'N/A')}"
                )

            # Write heartbeat to InfluxDB for dashboard visualization
            self._write_heartbeat_to_influxdb(node_name, payload, stats)

    def check_unhealthy_nodes(self):
        while True:
            time.sleep(60)
            current_time = time.time()
            with self.lock:
                for node, last_check in list(self.last_health_check.items()):
                    if current_time - last_check > 120:
                        if node in self.healthy_nodes:
                            logger.warning(f"{node} is now unhealthy!")
                            self.healthy_nodes.remove(node)
                            self.connected_nodes.discard(
                                node
                            )  # Also remove from connected nodes
                # Log the list of connected nodes
                logger.info(
                    f"Connected nodes: {', '.join(self.connected_nodes) or 'None'}"
                )

    def handle_data_point(self, station_id: str, payload: dict):
        data_type = payload.get("data_type")
        if data_type is None:
            logger.error("Payload does not contain 'data_type'")
            return

        point = self.data_handler.process_data(station_id, data_type, payload)
        if point is not None:
            self.write_to_influxdb(station_id, point)
        else:
            logger.warning("DataHandler returned None. Skipping write to InfluxDB.")

    def write_errors_callback(self, write_errors):
        for error in write_errors:
            logger.error(f"Failed to write data to InfluxDB. Error: {str(error)}")

    def write_to_influxdb(self, topic: str, point: Point):
        logger.debug(
            f"Preparing to write to InfluxDB: topic='{topic}', payload='{point}'"
        )
        try:
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=point)
            logger.debug(f"Sent to InfluxDB: topic='{topic}', payload='{point}'")
        except Exception as e:
            logger.error(
                f"Failed to write to InfluxDB: topic='{topic}', payload='{point}'. Error: {str(e)}"
            )

    def _write_heartbeat_to_influxdb(self, node_name: str, payload: dict, stats: dict):
        """Write heartbeat data to InfluxDB for dashboard visualization."""
        try:
            point = Point("node_health")
            point.tag("node_name", node_name)
            point.tag("status", payload.get("status", "unknown"))

            # Add stats as fields
            point.field("messages_sent", stats.get("messages_sent", 0))
            point.field("messages_failed", stats.get("messages_failed", 0))
            point.field("buffer_size", stats.get("buffer_size", 0))
            point.field("heartbeats_sent", stats.get("heartbeats_sent", 0))
            point.field("input_overflows", int(stats.get("input_overflows", 0) or 0))
            point.field("audio_active", 1 if stats.get("audio_active") else 0)
            audio_age = stats.get("audio_last_seen_ago_s")
            if audio_age is not None:
                point.field("audio_last_seen_ago_s", float(audio_age))
            point.field("online", 1)  # Indicator that node is online

            # Use heartbeat timestamp if available, otherwise current time
            timestamp = payload.get("timestamp")
            if timestamp:
                point.time(int(timestamp * 1e9), WritePrecision.NS)

            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=point)
            logger.debug(f"Wrote heartbeat to InfluxDB for {node_name}")
        except Exception as e:
            logger.warning(f"Failed to write heartbeat to InfluxDB: {e}")

    def handle_connection_status(self, payload):
        node_name = payload.get("node_name")
        if node_name is None:
            logger.error(f"Payload does not contain 'node_name': {payload}")
            return

        status = payload.get("status")
        if status is None:
            logger.error(f"Payload does not contain 'status': {payload}")
            return

        logger.info(f"Received connection status from {node_name}: {status}")

        if status == "connected":
            logger.info(f"Node {node_name} is connected.")
            self.connected_nodes.add(node_name)
        elif status == "disconnected":
            logger.warning(f"Node {node_name} is disconnected.")
            self.connected_nodes.discard(
                node_name
            )  # Use discard to avoid KeyError if node is not in the set
        else:
            logger.warning(f"Unknown status '{status}' received from {node_name}.")
