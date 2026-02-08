import logging
import os
import sys
import threading
import time
import uuid
from collections import deque
from queue import Queue

from zeroconf import ServiceBrowser, Zeroconf

# Add parent directory to path for common imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.transport import TransportConfig

logger = logging.getLogger(__name__)
SERVICE_TYPE = "_telemetryservice._tcp.local."


def get_mac_address():
    """Get MAC address as fallback identifier."""
    return ":".join(
        [
            "{:02x}".format((uuid.getnode() >> elements) & 0xFF)
            for elements in range(0, 2 * 6, 2)
        ][::-1]
    )


def get_pi_serial():
    """
    Get Raspberry Pi serial number (printed on board sticker).
    Returns last 8 chars which are unique per device.
    Falls back to MAC address on non-Pi systems.
    """
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    # Format: "Serial          : 10000000abcd1234"
                    # Return last 8 chars (unique part)
                    serial = line.strip().split(":")[1].strip()
                    return serial[-8:].upper()  # e.g., "ABCD1234"
    except (FileNotFoundError, IndexError, IOError):
        pass
    # Fallback for non-Pi systems
    return get_mac_address()


def get_node_id():
    """
    Get node identifier. Priority:
    1. NODE_NAME environment variable (explicit override)
    2. Hostname if customized (not default raspberrypi/bass-node)
    3. Pi serial number (printed on board - easy to label)
    4. MAC address (fallback)
    """
    # Explicit override
    if os.environ.get("NODE_NAME"):
        return os.environ["NODE_NAME"]

    # Custom hostname
    import socket
    hostname = socket.gethostname()
    if hostname and hostname not in ("raspberrypi", "bass-node", "localhost"):
        return hostname

    # Pi serial (printed on sticker)
    return get_pi_serial()


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


def discover_service(max_attempts=60, attempt_interval=5, fallback_broker=None):
    """Discover master node via Zeroconf with fallback option.

    Args:
        max_attempts: Maximum discovery attempts (default: 60 = 5 minutes at 5s intervals)
        attempt_interval: Seconds between discovery attempts (default: 5)
        fallback_broker: Optional broker address to use if discovery fails

    Returns:
        str: Broker address (discovered or fallback)

    Raises:
        Exception: If discovery fails and no fallback is provided
    """
    zeroconf = Zeroconf()
    listener = ServiceDiscoveryListener()
    browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)

    attempts = 0
    while not listener.broker_address and attempts < max_attempts:
        logger.info(
            f"Discovering master node... (attempt {attempts + 1}/{max_attempts})"
        )
        time.sleep(attempt_interval)
        attempts += 1

    zeroconf.close()

    if listener.broker_address:
        logger.info(f"Discovered master node at {listener.broker_address}")
        return listener.broker_address
    elif fallback_broker:
        logger.warning(
            f"Discovery failed after {max_attempts} attempts, "
            f"using fallback broker: {fallback_broker}"
        )
        return fallback_broker
    else:
        raise Exception(
            f"Service discovery failed after {max_attempts} attempts "
            f"({max_attempts * attempt_interval}s). "
            f"Ensure master node is running or provide fallback_broker in config."
        )


class TransportHandler:
    """Generic transport handler using pluggable transport layer.

    Features:
    - Offline buffering when transport is disconnected
    - Automatic buffer flush on reconnection
    - Periodic heartbeats with statistics
    - Thread-safe message queuing
    """

    def __init__(
        self,
        transport,
        topic,
        unit_name,
        heartbeat_interval=30,
        enable_heartbeat=True,
        offline_buffer_size=1000,
    ):
        self.transport = transport
        self.topic = topic
        self.unit_name = unit_name
        self.heartbeat_interval = heartbeat_interval
        self.enable_heartbeat = enable_heartbeat
        self.is_connected = False
        self._running = False
        self.message_queue = Queue()
        self.publisher_thread = None
        self.heartbeat_thread = None

        # Offline message buffering (in-memory, lost on crash - acceptable for telemetry)
        self.offline_buffer = deque(maxlen=offline_buffer_size)

        # Statistics
        self.messages_sent = 0
        self.messages_failed = 0
        self.messages_buffered = 0
        self.heartbeats_sent = 0

    def start(self):
        """Start transport connection."""
        self._running = True

        # Connect transport
        if not self.transport.connect():
            raise RuntimeError("Failed to connect transport")

        self.is_connected = True
        logger.info(f"Connected via {self.transport.__class__.__name__}")

        # Flush any buffered messages from previous session
        if self.offline_buffer:
            logger.info(f"Flushing {len(self.offline_buffer)} buffered messages")
            self._flush_offline_buffer()

        # Send connection status
        self.publish_message({"node_name": self.unit_name, "status": "connected"})

        # Start publisher thread
        self.publisher_thread = threading.Thread(target=self.publisher, daemon=True)
        self.publisher_thread.start()

        # Start heartbeat thread if enabled
        if self.enable_heartbeat:
            self.heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True
            )
            self.heartbeat_thread.start()
            logger.info(f"Heartbeat enabled (interval: {self.heartbeat_interval}s)")

    def stop(self):
        """Stop transport connection."""
        self._running = False
        self.is_connected = False
        if self.publisher_thread:
            self.publisher_thread.join(timeout=2)
        self.transport.disconnect()
        logger.info(
            f"Stopped. Buffered messages: {len(self.offline_buffer)} "
            f"(will be sent on next start)"
        )

    def _flush_offline_buffer(self):
        """Send buffered messages after reconnection."""
        while self.offline_buffer and self.is_connected:
            message = self.offline_buffer.popleft()
            try:
                success = self.transport.send(self.topic, message)
                if not success:
                    # Put it back at the front and stop flushing
                    self.offline_buffer.appendleft(message)
                    logger.warning("Failed to flush buffered message, will retry later")
                    break
            except Exception as e:
                logger.error(f"Error flushing buffer: {e}")
                self.offline_buffer.appendleft(message)
                break

    def _heartbeat_loop(self):
        """Send periodic heartbeats with node statistics."""
        while self._running:
            heartbeat = {
                "type": "heartbeat",
                "node_name": self.unit_name,
                "timestamp": time.time(),
                "status": "connected" if self.is_connected else "disconnected",
                "stats": {
                    "messages_sent": self.messages_sent,
                    "messages_failed": self.messages_failed,
                    "buffer_size": len(self.offline_buffer),
                    "heartbeats_sent": self.heartbeats_sent,
                },
            }
            self.publish_message(heartbeat)
            self.heartbeats_sent += 1
            time.sleep(self.heartbeat_interval)

    def publish_message(self, message):
        """Queue message for publishing."""
        self.message_queue.put(message)

    def publisher(self):
        """Publisher thread that handles message queue with offline buffering."""
        while self._running:
            try:
                message = self.message_queue.get(timeout=0.1)

                if self.is_connected and self.transport.is_connected():
                    # Try to send via transport
                    success = self.transport.send(self.topic, message)

                    if success:
                        self.messages_sent += 1
                        if self.messages_sent % 100 == 0:
                            logger.debug(
                                f"Transport stats: sent={self.messages_sent}, "
                                f"failed={self.messages_failed}, "
                                f"buffered={len(self.offline_buffer)}"
                            )
                    else:
                        # Send failed - buffer the message
                        self.offline_buffer.append(message)
                        self.messages_failed += 1
                        logger.debug(
                            f"Send failed, buffered message "
                            f"({len(self.offline_buffer)} in buffer)"
                        )
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

            except Exception as e:
                if self._running:
                    logger.debug(f"Publisher loop: {e}")
                continue


class TelemetrySender:
    def __init__(self, topic_suffix=None, transport_config=None, discovery_config=None):
        """
        Initialize telemetry sender.

        Args:
            topic_suffix: Topic suffix for messages (default: None)
            transport_config: Dictionary with transport configuration, or None to use MQTT discovery
                Example: {'type': 'lora', 'lora': {'frequency': 915, 'node_id': 1}}
                Example MQTT: {'type': 'mqtt', 'mqtt': {'broker': '192.168.1.100', 'port': 1883}}
            discovery_config: Dictionary with service discovery options (optional, for MQTT auto-discovery)
                Example: {
                    'max_attempts': 60,
                    'attempt_interval': 5,
                    'fallback_broker': '192.168.1.100'
                }
        """
        self.unit_name = get_node_id()
        logger.info(f"Node ID: {self.unit_name}")
        if topic_suffix:
            self.topic = f"{topic_suffix}/{self.unit_name}"
        else:
            self.topic = self.unit_name

        # Use transport layer for all cases (unified path)
        if transport_config:
            logger.info(
                f"Using transport: {transport_config.get('type', 'mqtt')}"
            )
            transport = self._create_transport(transport_config)
        else:
            # Auto-discover MQTT broker, then use MQTTTransport
            logger.info("Using MQTT with service discovery")

            # Extract discovery options
            discovery_config = discovery_config or {}
            max_attempts = discovery_config.get("max_attempts", 60)
            attempt_interval = discovery_config.get("attempt_interval", 5)
            fallback_broker = discovery_config.get("fallback_broker", None)

            try:
                broker_address = discover_service(
                    max_attempts=max_attempts,
                    attempt_interval=attempt_interval,
                    fallback_broker=fallback_broker,
                )
                logger.info(f"Discovered broker at {broker_address}")
            except Exception as e:
                logger.error(str(e))
                raise

            # Create MQTT transport with discovered broker
            mqtt_config = {
                "type": "mqtt",
                "mqtt": {
                    "broker": broker_address,
                    "port": 1883,
                    "connect_timeout": 10,
                    "connect_retries": 3,
                },
            }
            transport = self._create_transport(mqtt_config)

        # Use unified TransportHandler for all transports
        self.handler = TransportHandler(transport, self.topic, self.unit_name)
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
