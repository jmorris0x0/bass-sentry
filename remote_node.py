# Needs:
# pip install paho-mqtt zeroconf

# Needs:
# pip install paho-mqtt zeroconf

import paho.mqtt.client as mqtt
from zeroconf import ServiceBrowser, Zeroconf
import logging
import time
import random
import uuid
import json 
import signal
import sys


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def signal_handler(sig, frame):
    logger.info("Exiting remote node...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


SERVICE_TYPE = "_mymasterservice._tcp.local."


def get_mac_address():
    return ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) for elements in range(0, 2 * 6, 2)][::-1])


class ServiceDiscoveryListener:
    def __init__(self):
        self.broker_address = None

    def remove_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            addresses = info.parsed_addresses()
            if addresses:
                self.broker_address = addresses[0]

    def update_service(self, zeroconf, type, name):
        pass


def discover_service(max_attempts=10):
    zeroconf = Zeroconf()
    listener = ServiceDiscoveryListener()
    browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)
    attempts = 0
    while not listener.broker_address and attempts < max_attempts:
        logger.info("Attempting to discover master node...")
        time.sleep(5)
        attempts += 1
    zeroconf.close()
    if listener.broker_address:
        return listener.broker_address
    else:
        raise Exception("Service discovery failed after maximum attempts.")


class MQTTHandler:
    def __init__(self, broker_address, topic, unit_name):
        self.broker_address = broker_address
        self.topic = topic
        self.unit_name = unit_name
        self.client = mqtt.Client()
        self.reconnect_delay = 1

        # Setup MQTT handlers
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect


    def on_connect(self, client, userdata, flags, rc):
        logger.info(f"Connected to MQTT broker with result code {rc}")
    
        # Creating the heartbeat payload as a JSON string
        payload = json.dumps({
            "node": self.unit_name,
            "status": "connected"
        })

        client.publish(self.topic, payload)


    def on_disconnect(self, client, userdata, rc):
        logger.info(f"Disconnected with result code {rc}. Reconnecting in {self.reconnect_delay} seconds.")
        time.sleep(self.reconnect_delay)
        self.reconnect_delay = min(self.reconnect_delay * 2, 60)
        client.reconnect()

    def start(self):
        self.client.connect(self.broker_address, 1883, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def send_data(self, data):
        message = json.dumps(data)
        self.client.publish(self.topic, message)


def main():
    UNIT_NAME = get_mac_address()
    MQTT_TOPIC = f"remote_node/{UNIT_NAME}"
    
    try:
        broker_address = discover_service()
        print(f"Found master node at {broker_address}", flush=True)
    except Exception as e:
        print(str(e), flush=True)
        return

    handler = MQTTHandler(broker_address, MQTT_TOPIC, UNIT_NAME)
    handler.start()

    try:
        while True:
            json_data = {
                "station_id": UNIT_NAME,
                "timestamp": time.time_ns(),
                "frequency_1": 1, # Sample data 1
                "frequency_2": 2 # Sample data 2
            }

            logger.info(f"Sending data: {json_data}")
            handler.send_data(json_data)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping data transmission.", flush=True)
    finally:
        handler.stop()


if __name__ == "__main__":
    main()
