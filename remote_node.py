# Needs:
# pip install paho-mqtt zeroconf

# Needs:
# pip install paho-mqtt zeroconf

import paho.mqtt.client as mqtt
from zeroconf import ServiceBrowser, Zeroconf
import time
import random
import uuid
import json 

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
        print("Attempting to discover master node...")
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
        print(f"Connected to MQTT broker with result code {rc}")
        client.publish(self.topic, f"{self.unit_name} connected")

    def on_disconnect(self, client, userdata, rc):
        print(f"Disconnected with result code {rc}. Reconnecting in {self.reconnect_delay} seconds.")
        time.sleep(self.reconnect_delay)
        self.reconnect_delay = min(self.reconnect_delay * 2, 60)
        client.reconnect()

    def start(self):
        self.client.connect(self.broker_address, 1883, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def send_data(self, timestamp, data):
        message = json.dumps({'timestamp': timestamp, 'data': data})
        self.client.publish(self.topic, message)


def main():
    UNIT_NAME = get_mac_address()
    MQTT_TOPIC = f"remote_node/{UNIT_NAME}"
    
    try:
        broker_address = discover_service()
        print(f"Found master node at {broker_address}")
    except Exception as e:
        print(str(e))
        return

    handler = MQTTHandler(broker_address, MQTT_TOPIC, UNIT_NAME)
    handler.start()

    try:
        while True:
            random_data = random.random()
            timestamp = time.time()  # Generate a UNIX timestamp
            print(f"Sending data: {random_data} at timestamp: {timestamp}")
            handler.send_data(timestamp, random_data)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping data transmission.")
    finally:
        handler.stop()


if __name__ == "__main__":
    main()
