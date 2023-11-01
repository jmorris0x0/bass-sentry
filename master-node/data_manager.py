import logging
import json
import logging
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from data_handler import DataHandler


logger = logging.getLogger(__name__)


class DataManager:
    def __init__(
        self, influx_url, influx_token, influx_bucket, influx_org, mqtt_host, mqtt_port
    ):
        self.influx_client = self._connect_to_influx(
            influx_url, influx_token, influx_bucket, influx_org
        )
        self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
        self.write_api.errors_callback = self.write_errors_callback
        self.mqtt_client = self._connect_to_mqtt(mqtt_host, mqtt_port)
        self.healthy_nodes = set()
        self.last_health_check = {}
        self.lock = threading.Lock()
        self.connected_nodes = set()
        self.subscribed_topics = set()
        self.data_handler = DataHandler()

    def start(self):
        if not self.influx_client:
            logger.error("Could not connect to InfluxDB. Exiting...")
            sys.exit(1)

        self.mqtt_client.on_message = lambda client, userdata, message: self.on_message(
            client, userdata, message
        )

        self.mqtt_loop_start()

        threading.Thread(target=self.check_unhealthy_nodes, daemon=True).start()
        threading.Thread(
            target=self.subscribe_to_topics_periodically, daemon=True
        ).start()

        logger.info("Master node started successfully.")
        logger.info("Press Ctrl+C to exit...")

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
        client = mqtt.Client()
        client.on_connect = self.on_connect  # Set the on_connect callback
        client.connect(host, port, 60)
        return client

    def on_connect(self, client, userdata, flags, rc):
        logger.info(f"Connected to MQTT broker with result code {rc}")
        self.subscribe_to_topics()

    def get_all_topics(self):
        # Use wildcard '#' to subscribe to all topics
        return ["#"]

    def on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))

            # If payload contains a 'status' key, it's a connection status message
            if "status" in payload:
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
        data_type = payload.get('data_type')
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
        logger.debug(f"Preparing to write to InfluxDB: topic='{topic}', payload='{point}'")
        try:
            self.write_api.write(bucket="mybucket", org="myorg", record=point)
            logger.debug(f"Sent to InfluxDB: topic='{topic}', payload='{point}'")
        except Exception as e:
            logger.error(
                f"Failed to write to InfluxDB: topic='{topic}', payload='{point}'. Error: {str(e)}"
            )


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
