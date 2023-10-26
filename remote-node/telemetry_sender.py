import json
import logging
from queue import Queue
import threading
import time
import uuid
import paho.mqtt.client as mqtt
from zeroconf import ServiceBrowser, Zeroconf

logger = logging.getLogger(__name__)
SERVICE_TYPE = "_telemetryservice._tcp.local."

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
        self.heartbeat_interval = 5
        self.is_connected = False
        self.message_queue = Queue()  # Queue for storing messages

        # Setup MQTT handlers
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, rc):
        self.is_connected = True
        logger.info(f"Connected to MQTT broker with result code {rc}")
        self.publish_message({"node_name": self.unit_name, "status": "connected"})

    def on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        logger.info(f"Disconnected with result code {rc}. Trying to reconnect...")
        self.reconnect()

    def start(self):
        connected = False
        while not connected:
            try:
                self.client.connect(self.broker_address)
                connected = True
            except ConnectionRefusedError:
                logger.error(
                    "Connection refused. Retrying in {} seconds...".format(
                        self.reconnect_delay
                    )
                )
                time.sleep(self.reconnect_delay)
            except OSError as e:
                if e.errno == 65:
                    logger.error(
                        "No route to host. Retrying in {} seconds...".format(
                            self.reconnect_delay
                        )
                    )
                    time.sleep(self.reconnect_delay)
                else:
                    raise
        self.client.loop_start()
        self.publisher_thread = threading.Thread(target=self.publisher)
        self.publisher_thread.start()

    def reconnect(self):
        delay = self.reconnect_delay
        max_delay = 60  # maximum delay of 60 seconds
        while not self.is_connected:
            try:
                self.client.connect(self.broker_address)
                self.is_connected = True
            except (ConnectionRefusedError, OSError) as e:
                logger.error(f"Connection failed. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay = min(delay * 2, max_delay)  # double the delay, up to the maximum
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise  # re-raise unexpected exceptions

    def start(self):
        connected = False
        while not connected:
            try:
                self.client.connect(self.broker_address)
                connected = True
            except ConnectionRefusedError:
                logger.error(
                    "Connection refused. Retrying in {} seconds...".format(
                        self.reconnect_delay
                    )
                )
                time.sleep(self.reconnect_delay)
        self.client.loop_start()
        self.publisher_thread = threading.Thread(target=self.publisher)
        self.publisher_thread.start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        self.publisher_thread.join()

    def publish_message(self, message):
        self.message_queue.put(message)

    def publisher(self):
        while True:
            message = self.message_queue.get()
            if self.is_connected:
                try:
                    self.client.publish(self.topic, json.dumps(message))
                except ConnectionRefusedError:
                    logger.error("Connection refused. Attempting to reconnect...")
                    self.client.reconnect()
                    self.message_queue.put(message)
                    time.sleep(self.reconnect_delay)
                except Exception as e:
                    logger.error(f"Failed to send message: {e}")
                    self.message_queue.put(message)
                    time.sleep(self.reconnect_delay)
            else:
                logger.debug("Client is not connected. Skipping message.")
                self.message_queue.put(message)
                time.sleep(self.reconnect_delay)

    def send_heartbeat(self):
        while True:
            self.publish_message({"node_name": self.unit_name, "status": "connected"})
            time.sleep(self.heartbeat_interval)


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
        self.handler.publish_message(data)

    def stop(self):
        self.handler.stop()
