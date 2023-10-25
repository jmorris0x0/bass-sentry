#!/usr/bin/env python

import json
import logging
import os
import random
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt
import influxdb_client
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

healthy_nodes = set()
last_health_check = {}
lock = threading.Lock()


def connect_to_influx():
    bucket = os.environ.get("DOCKER_INFLUXDB_INIT_BUCKET")
    org = os.environ.get("DOCKER_INFLUXDB_INIT_ORG")
    token = os.environ.get("DOCKER_INFLUXDB_INIT_ADMIN_TOKEN", "")
    url = os.environ.get("INFLUXDB_HOST", "http://influxdb:8086")
    logger.info(f"Attempting to connect to InfluxDB with URL: {url}")

    try:
        client = influxdb_client.InfluxDBClient(
            url=url, token=token, database=bucket, org=org
        )

        logger.info("Successfully connected to InfluxDB!")
        logger.info(f"Token: {token}")

    except Exception as e:
        logger.error(f"Error connecting to InfluxDB: {e}")
        return None

    return client


def on_connect(mqtt_client, userdata, flags, rc):
    mqtt_client.subscribe("#")


def on_message(client, mqtt_client, userdata, msg):
    topic = msg.topic

    try:
        payload = json.loads(msg.payload.decode("utf-8"))

        # If payload contains a 'status' key, it's a connection status message
        if "status" in payload:
            handle_connection_status(payload)
        elif "health check" in payload:
            handle_health_check(payload)
        else:
            handle_data_point(client, topic, payload)
    except json.JSONDecodeError:
        logger.error(
            f"Failed to decode JSON from payload: {msg.payload.decode('utf-8')}"
        )


def handle_connection_status(payload):
    node = payload.get("node", "")
    status = payload.get("status", "")

    if status == "connected":
        logger.info(f"Node {node} connected")
    elif status == "disconnected":
        logger.info(f"Node {node} disconnected")


def handle_health_check(payload):
    with lock:
        node_name = payload.split()[0]
        if node_name not in healthy_nodes:
            logger.info(f"Discovered new node: {node_name}")
        healthy_nodes.add(node_name)
        last_health_check[node_name] = time.time()


def json_to_point(json_data):
    point = Point("dBFS")
    point.tag("station_id", json_data["station_id"])
    point.time(json_data["timestamp"], WritePrecision.NS)
    point.field("15-100Hz", json_data["15-100Hz"])
    # point.field("frequency_2", json_data["frequency_2"])

    return point


def handle_data_point(client, topic, payload):
    write_api = client.write_api(write_options=SYNCHRONOUS)

    point = json_to_point(payload)

    try:
        write_api.write(bucket="mybucket", org="myorg", record=point)
        logger.debug(f"Sent to InfluxDB for topic '{topic}' with payload '{payload}'")
    except Exception as e:
        logger.error(
            f"Failed to write data to InfluxDB for topic '{topic}' with payload '{payload}'. Error: {str(e)}"
        )


def check_unhealthy_nodes():
    while True:
        time.sleep(60)
        current_time = time.time()
        with lock:
            for node, last_check in last_health_check.items():
                if current_time - last_check > 120:
                    if node in healthy_nodes:
                        logger.warning(f"{node} is now unhealthy!")
                        healthy_nodes.remove(node)


def main():
    logger.info("Starting master node...")
    client = connect_to_influx()
    if not client:
        logger.error("Could not connect to InfluxDB. Exiting...")
        sys.exit(1)

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = lambda mc, ud, message: on_message(client, mc, ud, message)

    logger.info("Connecting to MQTT broker...")
    mqtt_client.connect("mosquitto", 1883, 60)

    logger.info("Starting MQTT loop...")
    mqtt_client.loop_start()

    threading.Thread(target=check_unhealthy_nodes, daemon=True).start()

    logger.info("Master node started successfully.")
    logger.info("Press Ctrl+C to exit...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("Exiting master node...")


if __name__ == "__main__":
    main()
