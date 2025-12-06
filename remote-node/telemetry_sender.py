import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import deque
from queue import Queue

import paho.mqtt.client as mqtt
from zeroconf import ServiceBrowser, Zeroconf

# Add parent directory to path for common imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.transport import create_transport, TransportConfig

logger = logging.getLogger(__name__)
SERVICE_TYPE = "_telemetryservice._tcp.local."

# MQTT Quality of Service levels
QOS_0_AT_MOST_ONCE = 0  # Fire and forget
QOS_1_AT_LEAST_ONCE = 1  # Acknowledged delivery
QOS_2_EXACTLY_ONCE = 2  # Assured delivery (slowest)


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
    def __init__(
        self,
        broker_address,
        topic,
        unit_name,
        qos=QOS_1_AT_LEAST_ONCE,
        max_reconnect_delay=300,
        offline_buffer_size=1000,
    ):
        self.broker_address = broker_address
        self.topic = topic
        self.unit_name = unit_name
        self.qos = qos
        self.max_reconnect_delay = max_reconnect_delay

        self.client = mqtt.Client()
        self.reconnect_delay = 1
        self.heartbeat_interval = 5
        self.is_connected = False

        # Offline message buffering
        self.offline_buffer = deque(maxlen=offline_buffer_size)
        self.message_queue = Queue()  # Queue for real-time messages

        # Statistics
        self.messages_sent = 0
        self.messages_failed = 0
        self.messages_buffered = 0

        # Setup MQTT handlers
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_publish = self.on_publish

    def on_connect(self, client, userdata, flags, rc):
        self.is_connected = True
        self.reconnect_delay = 1  # Reset backoff on successful connection
        logger.info(f"Connected to MQTT broker with result code {rc}, QoS={self.qos}")

        # Send connection status
        self.publish_message({"node_name": self.unit_name, "status": "connected"})

        # Flush offline buffer
        if self.offline_buffer:
            logger.info(f"Flushing {len(self.offline_buffer)} buffered messages")
            self._flush_offline_buffer()

    def on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        if rc != 0:
            logger.warning(
                f"Unexpected disconnect with code {rc}. Will reconnect automatically..."
            )
        else:
            logger.info("Disconnected normally")

    def on_publish(self, client, userdata, mid):
        """Called when message is published (QoS 1 or 2 only)."""
        self.messages_sent += 1
        if self.messages_sent % 100 == 0:
            logger.debug(
                f"MQTT stats: sent={self.messages_sent}, "
                f"failed={self.messages_failed}, "
                f"buffered={len(self.offline_buffer)}"
            )

    def _flush_offline_buffer(self):
        """Send buffered messages after reconnection."""
        while self.offline_buffer and self.is_connected:
            message = self.offline_buffer.popleft()
            try:
                result = self.client.publish(
                    self.topic, json.dumps(message), qos=self.qos
                )
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"Failed to flush message: {result.rc}")
                    # Put it back at the front
                    self.offline_buffer.appendleft(message)
                    break
            except Exception as e:
                logger.error(f"Error flushing buffer: {e}")
                self.offline_buffer.appendleft(message)
                break

    def start(self):
        """Start MQTT connection with automatic reconnection."""
        # Configure automatic reconnection
        self.client.reconnect_delay_set(min_delay=1, max_delay=self.max_reconnect_delay)

        connected = False
        delay = self.reconnect_delay

        while not connected:
            try:
                self.client.connect(self.broker_address)
                connected = True
            except ConnectionRefusedError:
                logger.error(f"Connection refused. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay = min(delay * 2, self.max_reconnect_delay)  # Exponential backoff
            except OSError as e:
                if e.errno == 65:  # No route to host
                    logger.error(f"No route to host. Retrying in {delay} seconds...")
                    # Recreate the MQTT client object
                    self.client = mqtt.Client()
                    self.client.on_connect = self.on_connect
                    self.client.on_disconnect = self.on_disconnect
                    self.client.on_publish = self.on_publish
                    time.sleep(delay)
                    delay = min(delay * 2, self.max_reconnect_delay)
                else:
                    raise  # re-raise for other OS errors

        self.client.loop_start()
        self.publisher_thread = threading.Thread(target=self.publisher, daemon=True)
        self.publisher_thread.start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        self.publisher_thread.join()

    def publish_message(self, message):
        self.message_queue.put(message)

    def publisher(self):
        """Publisher thread that handles message queue with offline buffering."""
        while True:
            message = self.message_queue.get()

            if self.is_connected:
                try:
                    result = self.client.publish(
                        self.topic, json.dumps(message), qos=self.qos
                    )

                    if result.rc == mqtt.MQTT_ERR_SUCCESS:
                        # Message queued successfully (QoS 1 will confirm delivery later)
                        pass
                    elif result.rc == mqtt.MQTT_ERR_NO_CONN:
                        # Not connected - buffer the message
                        self.offline_buffer.append(message)
                        self.messages_buffered += 1
                        logger.debug(
                            f"Buffered message (no connection): {len(self.offline_buffer)}/max"
                        )
                    else:
                        # Other error - buffer and try again
                        self.offline_buffer.append(message)
                        self.messages_failed += 1
                        logger.warning(
                            f"Publish failed with code {result.rc}, buffering message"
                        )

                except Exception as e:
                    # Unexpected error - buffer the message
                    logger.error(f"Failed to publish message: {e}")
                    self.offline_buffer.append(message)
                    self.messages_failed += 1

            else:
                # Not connected - buffer for later
                self.offline_buffer.append(message)
                self.messages_buffered += 1

                # Log buffer status periodically
                if len(self.offline_buffer) % 10 == 0:
                    logger.warning(
                        f"Offline: buffered {len(self.offline_buffer)} messages"
                    )

                # Don't spin too fast when offline
                time.sleep(0.1)

    def send_heartbeat(self):
        while True:
            self.publish_message({"node_name": self.unit_name, "status": "connected"})
            time.sleep(self.heartbeat_interval)


class TransportHandler:
    """Generic transport handler using pluggable transport layer."""

    def __init__(self, transport, topic, unit_name):
        self.transport = transport
        self.topic = topic
        self.unit_name = unit_name
        self.is_connected = False
        self.message_queue = Queue()
        self.publisher_thread = None

        # Statistics
        self.messages_sent = 0
        self.messages_failed = 0

    def start(self):
        """Start transport connection."""
        # Connect transport
        if not self.transport.connect():
            raise RuntimeError("Failed to connect transport")

        self.is_connected = True
        logger.info(f"Connected via {self.transport.__class__.__name__}")

        # Send connection status
        self.publish_message({"node_name": self.unit_name, "status": "connected"})

        # Start publisher thread
        self.publisher_thread = threading.Thread(target=self.publisher, daemon=True)
        self.publisher_thread.start()

    def stop(self):
        """Stop transport connection."""
        self.is_connected = False
        if self.publisher_thread:
            self.publisher_thread.join(timeout=2)
        self.transport.disconnect()

    def publish_message(self, message):
        """Queue message for publishing."""
        self.message_queue.put(message)

    def publisher(self):
        """Publisher thread that handles message queue."""
        while self.is_connected:
            try:
                message = self.message_queue.get(timeout=0.1)

                # Send via transport
                success = self.transport.send(self.topic, message)

                if success:
                    self.messages_sent += 1
                    if self.messages_sent % 100 == 0:
                        logger.debug(
                            f"Transport stats: sent={self.messages_sent}, failed={self.messages_failed}"
                        )
                else:
                    self.messages_failed += 1
                    logger.warning(f"Failed to send message via transport")

            except Exception as e:
                if self.is_connected:  # Only log if we're still supposed to be running
                    logger.debug(f"Publisher loop: {e}")
                continue


class TelemetrySender:
    def __init__(self, topic_suffix=None, transport_config=None):
        """
        Initialize telemetry sender.

        Args:
            topic_suffix: Topic suffix for messages (default: None)
            transport_config: Dictionary with transport configuration, or None to use MQTT discovery
                Example: {'type': 'lora', 'lora': {'frequency': 915, 'node_id': 1}}
        """
        self.unit_name = get_mac_address()
        if topic_suffix:
            self.topic = f"{topic_suffix}/{self.unit_name}"
        else:
            self.topic = self.unit_name

        # Use transport layer if config provided, otherwise fall back to MQTT discovery
        if transport_config:
            logger.info(
                f"Using pluggable transport: {transport_config.get('type', 'unknown')}"
            )
            transport = self._create_transport(transport_config)
            self.handler = TransportHandler(transport, self.topic, self.unit_name)
        else:
            # Legacy MQTT with service discovery (backward compatible)
            logger.info("Using legacy MQTT with service discovery")
            try:
                broker_address = discover_service()
                logger.info(f"Found master node at {broker_address}")
            except Exception as e:
                logger.error(str(e))
                raise

            self.handler = MQTTHandler(broker_address, self.topic, self.unit_name)

        self.handler.start()

    def _create_transport(self, config_dict):
        """Create transport from configuration dictionary."""
        try:
            config = TransportConfig.from_dict(config_dict)
            from common.transport import get_transport

            return get_transport(config)
        except Exception as e:
            logger.error(f"Failed to create transport: {e}")
            raise

    def send_data(self, data):
        logger.debug(f"Sending data: {data}")
        self.handler.publish_message(data)

    def stop(self):
        self.handler.stop()
