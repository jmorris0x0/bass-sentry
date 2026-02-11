"""
MQTT Transport Implementation

Uses MQTT over WiFi/Ethernet for communication.
This is the default transport - works for most venues.
"""

import json
import logging
import time
from typing import Callable, Dict, Any

import paho.mqtt.client as mqtt

from common.transport import Transport

logger = logging.getLogger(__name__)


class MQTTTransport(Transport):
    """MQTT transport implementation (default for WiFi)."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize MQTT transport.

        Config options:
            broker: MQTT broker address (default: 'localhost')
            port: MQTT broker port (default: 1883)
            qos: Quality of Service 0, 1, or 2 (default: 1)
            client_id: Optional client ID
            username: Optional authentication
            password: Optional authentication
            keepalive: Keepalive interval in seconds (default: 60)
            connect_timeout: Timeout for connection attempt in seconds (default: 10)
            connect_retries: Number of connection retry attempts (default: 3)
            retry_backoff: Backoff multiplier for retries (default: 2.0)
        """
        super().__init__(config)

        self.broker = config.get("broker", "localhost")
        self.port = config.get("port", 1883)
        self.qos = config.get("qos", 1)
        self.client_id = config.get("client_id", None)
        self.keepalive = config.get("keepalive", 60)

        # Connection retry settings
        self.connect_timeout = config.get("connect_timeout", 10)
        self.connect_retries = config.get("connect_retries", 3)
        self.retry_backoff = config.get("retry_backoff", 2.0)

        # Create MQTT client (v2 callback API)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)

        # Set authentication if provided
        username = config.get("username")
        password = config.get("password")
        if username and password:
            self.client.username_pw_set(username, password)

        # Set callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_failed": 0,
            "reconnects": 0,
            "connection_attempts": 0,
        }

    def connect(self) -> bool:
        """Connect to MQTT broker with retry logic.

        Attempts to connect up to connect_retries times with exponential backoff.

        Returns:
            bool: True if connected successfully, False otherwise
        """
        for attempt in range(self.connect_retries):
            self.stats["connection_attempts"] += 1

            try:
                logger.info(
                    f"Connecting to MQTT broker at {self.broker}:{self.port} "
                    f"(attempt {attempt + 1}/{self.connect_retries})"
                )
                self.client.connect(self.broker, self.port, self.keepalive)
                self.client.loop_start()

                # Wait for connection with configurable timeout
                iterations = int(self.connect_timeout * 10)
                for _ in range(iterations):
                    if self.connected:
                        logger.info("MQTT transport connected")
                        return True
                    time.sleep(0.1)

                logger.warning(
                    f"Connection attempt {attempt + 1} timed out after {self.connect_timeout}s"
                )
                self.client.loop_stop()

            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")

            # Retry with backoff (except on last attempt)
            if attempt < self.connect_retries - 1:
                delay = self.retry_backoff ** attempt
                logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)

        logger.error(
            f"Failed to connect to MQTT broker after {self.connect_retries} attempts"
        )
        return False

    def disconnect(self):
        """Disconnect from MQTT broker."""
        logger.info("Disconnecting MQTT transport")
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False

    def send(self, topic: str, data: Dict[str, Any], **kwargs) -> bool:
        """
        Send data via MQTT.

        Args:
            topic: MQTT topic
            data: Data to send (will be JSON-serialized)
            **kwargs: Optional 'qos' override

        Returns:
            bool: True if published successfully
        """
        if not self.connected:
            logger.warning("MQTT not connected, cannot send")
            self.stats["messages_failed"] += 1
            return False

        try:
            # Serialize data
            payload = json.dumps(data)

            # Get QoS (use instance default or override)
            qos = kwargs.get("qos", self.qos)

            # Publish
            result = self.client.publish(topic, payload, qos=qos)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.stats["messages_sent"] += 1
                return True
            else:
                logger.error(f"MQTT publish failed: {result.rc}")
                self.stats["messages_failed"] += 1
                return False

        except Exception as e:
            logger.error(f"MQTT send error: {e}")
            self.stats["messages_failed"] += 1
            return False

    def subscribe(self, topic: str, callback: Callable[[str, Dict], None]):
        """
        Subscribe to MQTT topic.

        Args:
            topic: MQTT topic pattern (supports wildcards: +, #)
            callback: Function called with (topic, data) when message arrives
        """
        logger.info(f"Subscribing to MQTT topic: {topic}")

        # Store callback
        self.callbacks[topic] = callback

        # Subscribe
        self.client.subscribe(topic, qos=self.qos)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback (v2 API)."""
        if reason_code == 0:
            logger.info("MQTT connected successfully")
            self.connected = True

            # Resubscribe to all topics (in case of reconnect)
            for topic in self.callbacks.keys():
                logger.info(f"Resubscribing to {topic}")
                self.client.subscribe(topic, qos=self.qos)
        else:
            logger.error(f"MQTT connection failed with code {reason_code}")
            self.connected = False

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """MQTT disconnection callback (v2 API)."""
        self.connected = False
        if reason_code != 0:
            logger.warning(f"MQTT unexpected disconnect (rc={reason_code}), will reconnect")
            self.stats["reconnects"] += 1
        else:
            logger.info("MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        """MQTT message received callback."""
        try:
            # Parse JSON payload
            data = json.loads(msg.payload.decode())

            # Find matching callback(s)
            for topic_pattern, callback in self.callbacks.items():
                if mqtt.topic_matches_sub(topic_pattern, msg.topic):
                    callback(msg.topic, data)

            self.stats["messages_received"] += 1

        except json.JSONDecodeError as e:
            logger.error(f"MQTT message decode error: {e}")
        except Exception as e:
            logger.error(f"MQTT message handling error: {e}")

    def get_stats(self) -> Dict[str, int]:
        """Get transport statistics."""
        return {**self.stats, "connected": self.connected}
