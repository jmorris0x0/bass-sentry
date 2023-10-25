import json
import logging
import time
import uuid
import paho.mqtt.client as mqtt
from zeroconf import ServiceBrowser, Zeroconf

logger = logging.getLogger(__name__)
SERVICE_TYPE = "_mymasterservice._tcp.local."

# TODO: Add QOS for both remote and master


def get_mac_address():
    return ":".join(
        [
            "{:02x}".format((uuid.getnode() >> elements) & 0xFF)
            for elements in range(0, 2 * 6, 2)
        ][::-1]
    )


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


def discover_service(max_attempts=10000000):
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
        payload = json.dumps({"node": self.unit_name, "status": "connected"})

        client.publish(self.topic, payload)

    def on_disconnect(self, client, userdata, rc):
        logger.info(
            f"Disconnected with result code {rc}. Reconnecting in {self.reconnect_delay} seconds."
        )
        time.sleep(self.reconnect_delay)
        self.reconnect_delay = min(self.reconnect_delay * 2, 60)
        client.reconnect()

    def start(self):
        retry_interval = 0.25  # Initial retry interval in seconds
        max_retry_interval = 10  # Maximum retry interval in seconds

        while True:
            try:
                self.client.connect(self.broker_address, 1883, 60)
                break  # Exit the loop if the connection is successful
            except OSError as e:
                if e.errno == 65:
                    logger.warning(
                        f"Failed to connect to the broker. Retrying in {retry_interval} s..."
                    )
                    time.sleep(retry_interval)
                    retry_interval = min(retry_interval * 2, max_retry_interval)
                else:
                    raise  # Reraise the exception if it is not "No route to host"

        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def send_data(self, data):
        message = json.dumps(data)
        self.client.publish(self.topic, message)


class TelemetrySender:
    def __init__(self, topic_suffix=None):
        self.unit_name = get_mac_address()
        if topic_suffix:
            self.topic = f"{topic_suffix}/{self.unit_name}"
        else:
            self.topic = self.unit_name

        try:
            self.broker_address = discover_service()
            logger.info(f"Found master node at {self.broker_address}")
        except Exception as e:
            logger.error(str(e))
            raise

        self.handler = MQTTHandler(self.broker_address, self.topic, self.unit_name)
        self.handler.start()

    def send_data(self, data):
        logger.info(f"Sending data: {data}")
        self.handler.send_data(data)

    def stop(self):
        self.handler.stop()
