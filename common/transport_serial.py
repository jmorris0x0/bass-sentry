"""
Serial Transport Implementation

Uses RS-232/USB serial for communication.
Perfect for:
- Direct wired connections (debugging, testing)
- Point-to-point links (no network needed)
- Reliable short-distance communication
- Development and troubleshooting

Hardware Requirements:
- USB serial adapter (CP2102, FTDI, CH340)
- Or direct UART connection (Pi GPIO pins)

Bandwidth: 9600-115200 baud (sufficient for 16 kb/s per node)
Range: 15m (RS-232), 5m (USB), 1000m+ (RS-485)
"""

import json
import logging
import threading
import time
from typing import Callable, Dict, Any, Optional

from common.transport import Transport

logger = logging.getLogger(__name__)

# Try to import serial library (optional dependency)
try:
    import serial

    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.warning("Serial library not available. Install with: pip install pyserial")


class SerialTransport(Transport):
    """Serial transport implementation for wired communication."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Serial transport.

        Config options:
            port: Serial port (e.g., '/dev/ttyUSB0', 'COM3')
            baudrate: Communication speed (default: 115200)
            timeout: Read timeout in seconds (default: 1.0)
            node_id: This node's ID (default: 0)
        """
        super().__init__(config)

        if not SERIAL_AVAILABLE:
            raise RuntimeError(
                "Serial library not installed. Install with: pip install pyserial"
            )

        self.port = config.get("port")
        if not self.port:
            raise ValueError("Serial transport requires 'port' in config")

        self.baudrate = config.get("baudrate", 115200)
        self.timeout = config.get("timeout", 1.0)
        self.node_id = config.get("node_id", 0)

        # Serial connection (initialized in connect())
        self.serial = None

        # Receive thread
        self.receive_thread = None
        self.running = False

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_failed": 0,
            "parse_errors": 0,
        }

    def connect(self) -> bool:
        """Open serial port."""
        try:
            logger.info(f"Opening serial port {self.port} at {self.baudrate} baud")

            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )

            # Clear buffers
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

            self.connected = True
            logger.info(f"Serial port opened: {self.serial.name}")

            # Start receive thread
            self.running = True
            self.receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self.receive_thread.start()

            return True

        except serial.SerialException as e:
            logger.error(f"Serial port open failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Close serial port."""
        logger.info("Disconnecting Serial transport")
        self.running = False
        if self.receive_thread:
            self.receive_thread.join(timeout=2)
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False

    def send(self, topic: str, data: Dict[str, Any], **kwargs) -> bool:
        """
        Send data via serial.

        Serial Message Format:
        <START><JSON><END>

        Where:
        - START = 0x02 (STX - Start of Text)
        - JSON = {"topic": "...", "data": {...}}
        - END = 0x03 (ETX - End of Text)

        Args:
            topic: Topic string (will be encoded in message)
            data: Data to send (JSON-serialized)
            **kwargs: Optional parameters

        Returns:
            bool: True if sent successfully
        """
        if not self.connected or not self.serial:
            logger.warning("Serial not connected, cannot send")
            self.stats["messages_failed"] += 1
            return False

        try:
            # Build message
            message = {
                "topic": topic,
                "data": data,
                "node_id": self.node_id,
                "timestamp": time.time(),
            }

            # Serialize to JSON
            json_str = json.dumps(message)

            # Frame with STX/ETX
            frame = b"\x02" + json_str.encode("utf-8") + b"\x03"

            # Send
            self.serial.write(frame)
            self.serial.flush()

            self.stats["messages_sent"] += 1
            logger.debug(f"Serial sent {len(frame)} bytes")
            return True

        except (serial.SerialException, OSError) as e:
            logger.error(f"Serial send error: {e}")
            self.stats["messages_failed"] += 1
            return False

    def subscribe(self, topic: str, callback: Callable[[str, Dict], None]):
        """
        Subscribe to topic pattern.

        Note: Serial doesn't have built-in pub/sub, so we filter in software.

        Args:
            topic: Topic pattern (supports wildcards: + for single level, # for multi-level)
            callback: Function called with (topic, data) when message arrives
        """
        logger.info(f"Registering Serial callback for topic: {topic}")
        self.callbacks[topic] = callback

    def _receive_loop(self):
        """Background thread to receive serial messages."""
        logger.info("Serial receive loop started")

        buffer = bytearray()

        while self.running:
            try:
                # Read available bytes
                if self.serial.in_waiting > 0:
                    chunk = self.serial.read(self.serial.in_waiting)
                    buffer.extend(chunk)

                    # Look for complete frames (STX...ETX)
                    while b"\x02" in buffer and b"\x03" in buffer:
                        start = buffer.index(b"\x02")
                        try:
                            end = buffer.index(b"\x03", start)
                        except ValueError:
                            break  # No complete frame yet

                        # Extract frame
                        frame = buffer[start + 1 : end]
                        buffer = buffer[end + 1 :]  # Remove processed frame

                        # Process frame
                        self._handle_frame(frame)

                else:
                    # No data available, sleep briefly
                    time.sleep(0.01)

            except serial.SerialException as e:
                logger.error(f"Serial receive error: {e}")
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Unexpected error in receive loop: {e}")
                time.sleep(0.1)

        logger.info("Serial receive loop stopped")

    def _handle_frame(self, frame: bytes):
        """
        Parse and handle received serial frame.

        Args:
            frame: Raw frame bytes (JSON)
        """
        try:
            # Decode JSON
            message = json.loads(frame.decode("utf-8"))

            # Extract topic and data
            topic = message.get("topic")
            data = message.get("data")

            if not topic or data is None:
                logger.warning("Serial message missing topic or data")
                return

            # Call matching callbacks
            for topic_pattern, callback in self.callbacks.items():
                if self._topic_matches(topic_pattern, topic):
                    callback(topic, data)

            self.stats["messages_received"] += 1
            logger.debug(f"Serial received message on topic: {topic}")

        except json.JSONDecodeError as e:
            logger.error(f"Serial frame JSON decode error: {e}")
            self.stats["parse_errors"] += 1
        except Exception as e:
            logger.error(f"Serial frame handling error: {e}")
            self.stats["parse_errors"] += 1

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """
        Check if topic matches pattern (with wildcards).

        Supports:
        - + : Single level wildcard
        - # : Multi-level wildcard

        Args:
            pattern: Pattern with wildcards
            topic: Actual topic

        Returns:
            bool: True if matches
        """
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")

        i = 0
        j = 0

        while i < len(pattern_parts) and j < len(topic_parts):
            if pattern_parts[i] == "#":
                return True  # Multi-level wildcard matches rest
            elif pattern_parts[i] == "+":
                # Single level wildcard
                i += 1
                j += 1
            elif pattern_parts[i] == topic_parts[j]:
                i += 1
                j += 1
            else:
                return False

        return i == len(pattern_parts) and j == len(topic_parts)

    def get_stats(self) -> Dict[str, Any]:
        """Get transport statistics."""
        return {
            **self.stats,
            "connected": self.connected,
            "port": self.port,
            "baudrate": self.baudrate,
        }


# Utility functions
def list_serial_ports():
    """
    List available serial ports.

    Returns:
        list: Available port names
    """
    if not SERIAL_AVAILABLE:
        logger.error("pyserial not installed")
        return []

    from serial.tools import list_ports

    ports = list_ports.comports()

    return [
        {"device": port.device, "description": port.description, "hwid": port.hwid}
        for port in ports
    ]
