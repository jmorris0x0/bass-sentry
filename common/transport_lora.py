"""
LoRa Transport Implementation

Uses LoRa (Long Range) radio for communication.
Perfect for:
- Outdoor festivals (2-10km range)
- Large venues
- Areas with poor WiFi
- Concrete buildings (better penetration than WiFi)

Hardware Requirements:
- Dragino LoRa/GPS HAT for Raspberry Pi ($25)
- RAK Wireless LoRa module ($20-40)
- Adafruit RFM95W LoRa Radio ($20)

Bandwidth: ~0.3-50 kb/s (perfect for 16 kb/s per node)
Range: 2-10 km (outdoor), 1-2 km (urban)
"""

import json
import logging
import struct
import time
from typing import Callable, Dict, Any, Optional
import threading

from common.transport import Transport

logger = logging.getLogger(__name__)

# Try to import LoRa library (optional dependency)
try:
    from adafruit_rfm import rfm9x
    import board
    import busio
    import digitalio

    LORA_AVAILABLE = True
except ImportError:
    LORA_AVAILABLE = False
    logger.warning(
        "LoRa libraries not available. Install with: pip install adafruit-circuitpython-rfm9x"
    )


class LoRaTransport(Transport):
    """LoRa transport implementation for long-range communication."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize LoRa transport.

        Config options:
            frequency: Radio frequency in MHz (default: 915 for US, 868 for EU, 433 for Asia)
            tx_power: Transmit power in dBm, 5-23 (default: 20)
            spreading_factor: 7-12, higher = longer range but slower (default: 7)
            bandwidth: 7.8, 10.4, 15.6, 20.8, 31.25, 41.7, 62.5, 125, 250, 500 kHz (default: 125)
            coding_rate: 5-8 (default: 5)
            node_id: This node's ID (0-255, default: auto-assign)
            gateway_id: Gateway/master node ID (default: 0)
            max_packet_size: Maximum packet size in bytes (default: 250)
            network_id: Network ID for isolation (0x00-0xFF, default: 0x12 - CHANGE THIS!)
            encryption_key: Optional 16-byte encryption key (hex string or bytes)
        """
        super().__init__(config)

        if not LORA_AVAILABLE:
            raise RuntimeError(
                "LoRa libraries not installed. Install with: pip install adafruit-circuitpython-rfm9x"
            )

        self.frequency = config.get("frequency", 915)  # MHz
        self.tx_power = config.get("tx_power", 20)  # dBm
        self.spreading_factor = config.get("spreading_factor", 7)
        self.bandwidth = config.get("bandwidth", 125_000)  # Hz
        self.coding_rate = config.get("coding_rate", 5)
        self.node_id = config.get("node_id", None)  # Auto-assign if None
        self.gateway_id = config.get("gateway_id", 0)
        self.max_packet_size = config.get("max_packet_size", 250)

        # Network isolation (sync word)
        self.network_id = config.get(
            "network_id", 0x12
        )  # Default - USERS SHOULD CHANGE THIS!

        # Optional encryption
        self.encryption_key = config.get("encryption_key", None)
        if self.encryption_key:
            self._init_encryption()

        # LoRa radio (initialized in connect())
        self.radio = None

        # Receive thread
        self.receive_thread = None
        self.running = False

        # Message sequence number
        self.sequence = 0

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_failed": 0,
            "messages_rejected": 0,  # Wrong network ID or decryption failed
            "rssi_last": None,  # Signal strength of last received packet
            "snr_last": None,  # SNR of last received packet
        }

    def _init_encryption(self):
        """Initialize AES encryption."""
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
            import secrets

            # Convert hex string to bytes if needed
            if isinstance(self.encryption_key, str):
                self.encryption_key = bytes.fromhex(self.encryption_key)

            if len(self.encryption_key) != 16:
                raise ValueError("Encryption key must be 16 bytes (128-bit AES)")

            self.cipher_backend = default_backend()
            logger.info("LoRa encryption enabled (AES-128)")

        except ImportError:
            logger.error(
                "Encryption requires 'cryptography' library: pip install cryptography"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to initialize encryption: {e}")
            raise

    def _encrypt(self, data: bytes) -> bytes:
        """Encrypt data with AES-CTR."""
        if not self.encryption_key:
            return data

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        import secrets

        # Generate random nonce (12 bytes for CTR mode)
        nonce = secrets.token_bytes(12)

        # Pad nonce to 16 bytes for AES block size
        iv = nonce + b"\x00\x00\x00\x01"

        # Create cipher
        cipher = Cipher(
            algorithms.AES(self.encryption_key),
            modes.CTR(iv),
            backend=self.cipher_backend,
        )
        encryptor = cipher.encryptor()

        # Encrypt
        ciphertext = encryptor.update(data) + encryptor.finalize()

        # Prepend nonce to ciphertext
        return nonce + ciphertext

    def _decrypt(self, data: bytes) -> bytes:
        """Decrypt data with AES-CTR."""
        if not self.encryption_key:
            return data

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        if len(data) < 12:
            raise ValueError("Encrypted data too short")

        # Extract nonce and ciphertext
        nonce = data[:12]
        ciphertext = data[12:]

        # Pad nonce to 16 bytes
        iv = nonce + b"\x00\x00\x00\x01"

        # Create cipher
        cipher = Cipher(
            algorithms.AES(self.encryption_key),
            modes.CTR(iv),
            backend=self.cipher_backend,
        )
        decryptor = cipher.decryptor()

        # Decrypt
        return decryptor.update(ciphertext) + decryptor.finalize()

    def connect(self) -> bool:
        """Initialize LoRa radio."""
        try:
            logger.info(f"Initializing LoRa radio at {self.frequency} MHz")

            # Initialize SPI bus
            spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)

            # Initialize LoRa chip select and reset pins
            cs = digitalio.DigitalInOut(board.CE1)
            reset = digitalio.DigitalInOut(board.D25)

            # Initialize radio
            self.radio = rfm9x.RFM9x(spi, cs, reset, self.frequency)

            # Configure radio parameters
            self.radio.tx_power = self.tx_power
            self.radio.spreading_factor = self.spreading_factor
            self.radio.signal_bandwidth = self.bandwidth
            self.radio.coding_rate = self.coding_rate

            # Enable CRC
            self.radio.enable_crc = True

            # Set sync word (network ID) for network isolation
            # Only radios with matching sync word can communicate
            self.radio.sync_word = self.network_id

            self.connected = True
            logger.info(
                f"LoRa radio initialized: SF={self.spreading_factor}, "
                f"BW={self.bandwidth/1000}kHz, TxPower={self.tx_power}dBm, "
                f"NetworkID=0x{self.network_id:02X}, "
                f"Encryption={'enabled' if self.encryption_key else 'disabled'}"
            )

            # Start receive thread
            self.running = True
            self.receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self.receive_thread.start()

            return True

        except Exception as e:
            logger.error(f"LoRa initialization failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Shutdown LoRa radio."""
        logger.info("Disconnecting LoRa transport")
        self.running = False
        if self.receive_thread:
            self.receive_thread.join(timeout=2)
        self.connected = False

    def send(self, topic: str, data: Dict[str, Any], **kwargs) -> bool:
        """
        Send data via LoRa.

        LoRa Packet Format:
        [Header: 8 bytes][Payload: variable]

        Header:
        - Destination ID (1 byte)
        - Source ID (1 byte)
        - Sequence Number (2 bytes)
        - Topic Length (1 byte)
        - Payload Length (2 bytes)
        - Reserved (1 byte)

        Args:
            topic: Topic string (will be encoded in packet)
            data: Data to send (JSON-serialized)
            **kwargs: Optional 'destination' node ID override

        Returns:
            bool: True if sent successfully
        """
        if not self.connected or not self.radio:
            logger.warning("LoRa not connected, cannot send")
            self.stats["messages_failed"] += 1
            return False

        try:
            # Serialize data
            payload = json.dumps(data).encode("utf-8")
            topic_bytes = topic.encode("utf-8")

            # Check size limits
            total_size = 8 + len(topic_bytes) + len(payload)
            if total_size > self.max_packet_size:
                # Try compressing (msgpack is smaller than JSON)
                try:
                    import msgpack

                    payload = msgpack.packb(data)
                    total_size = 8 + len(topic_bytes) + len(payload)
                except:
                    pass

                if total_size > self.max_packet_size:
                    logger.error(
                        f"Packet too large: {total_size} > {self.max_packet_size} bytes"
                    )
                    self.stats["messages_failed"] += 1
                    return False

            # Build packet header
            dest_id = kwargs.get("destination", self.gateway_id)
            src_id = self.node_id or 255  # 255 = auto-assigned

            header = struct.pack(
                "BBHBHB",
                dest_id,  # Destination ID
                src_id,  # Source ID
                self.sequence,  # Sequence number
                len(topic_bytes),  # Topic length
                len(payload),  # Payload length
                0,  # Reserved
            )

            # Build complete packet
            packet = header + topic_bytes + payload

            # Encrypt if encryption is enabled
            if self.encryption_key:
                packet = self._encrypt(packet)

            # Send via LoRa
            self.radio.send(packet)

            # Increment sequence
            self.sequence = (self.sequence + 1) % 65536

            self.stats["messages_sent"] += 1
            logger.debug(f"LoRa sent {len(packet)} bytes to node {dest_id}")
            return True

        except Exception as e:
            logger.error(f"LoRa send error: {e}")
            self.stats["messages_failed"] += 1
            return False

    def subscribe(self, topic: str, callback: Callable[[str, Dict], None]):
        """
        Subscribe to topic pattern.

        Note: LoRa doesn't have built-in pub/sub, so we filter in software.

        Args:
            topic: Topic pattern (supports wildcards: + for single level, # for multi-level)
            callback: Function called with (topic, data) when message arrives
        """
        logger.info(f"Registering LoRa callback for topic: {topic}")
        self.callbacks[topic] = callback

    def _receive_loop(self):
        """Background thread to receive LoRa packets."""
        logger.info("LoRa receive loop started")

        while self.running:
            try:
                # Check for packet (non-blocking with timeout)
                packet = self.radio.receive(timeout=0.5)

                if packet is not None:
                    self._handle_packet(packet)

            except Exception as e:
                logger.error(f"LoRa receive error: {e}")
                time.sleep(0.1)

        logger.info("LoRa receive loop stopped")

    def _handle_packet(self, packet: bytes):
        """
        Parse and handle received LoRa packet.

        Args:
            packet: Raw received packet bytes
        """
        try:
            # Decrypt if encryption is enabled
            if self.encryption_key:
                try:
                    packet = self._decrypt(packet)
                except Exception as e:
                    logger.debug(
                        f"Failed to decrypt packet (wrong key or network): {e}"
                    )
                    self.stats["messages_rejected"] += 1
                    return

            # Check minimum size
            if len(packet) < 8:
                logger.warning(f"LoRa packet too short: {len(packet)} bytes")
                self.stats["messages_rejected"] += 1
                return

            # Parse header
            dest_id, src_id, seq, topic_len, payload_len, _ = struct.unpack(
                "BBHBHB", packet[:8]
            )

            # Check if packet is for us (destination filtering)
            if dest_id != 255 and dest_id != (self.node_id or 255):
                # Not for us, ignore
                # NOTE: Sync word already filtered at radio level,
                # so we only see packets from our network
                logger.debug(f"Packet not for us (dest={dest_id}, us={self.node_id})")
                self.stats["messages_rejected"] += 1
                return

            # Extract topic and payload
            topic_start = 8
            topic_end = topic_start + topic_len
            payload_start = topic_end
            payload_end = payload_start + payload_len

            if payload_end > len(packet):
                logger.warning("LoRa packet payload length mismatch")
                return

            topic = packet[topic_start:topic_end].decode("utf-8")
            payload_bytes = packet[payload_start:payload_end]

            # Try JSON first, fall back to msgpack
            try:
                data = json.loads(payload_bytes.decode("utf-8"))
            except:
                try:
                    import msgpack

                    data = msgpack.unpackb(payload_bytes)
                except:
                    logger.error("LoRa payload decode failed")
                    return

            # Update signal quality stats
            self.stats["rssi_last"] = self.radio.last_rssi
            self.stats["snr_last"] = self.radio.last_snr

            # Call matching callbacks
            for topic_pattern, callback in self.callbacks.items():
                if self._topic_matches(topic_pattern, topic):
                    callback(topic, data)

            self.stats["messages_received"] += 1
            logger.debug(
                f"LoRa received from node {src_id}, RSSI={self.radio.last_rssi}dBm, SNR={self.radio.last_snr}dB"
            )

        except Exception as e:
            logger.error(f"LoRa packet handling error: {e}")

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
            "spreading_factor": self.spreading_factor,
            "bandwidth_khz": self.bandwidth / 1000,
            "tx_power_dbm": self.tx_power,
        }


# Convenience function for LoRa-specific features
def estimate_lora_range(
    spreading_factor: int, tx_power: int, environment: str = "urban"
) -> float:
    """
    Estimate LoRa range based on parameters.

    Args:
        spreading_factor: 7-12
        tx_power: Transmit power in dBm (5-23)
        environment: 'urban', 'suburban', or 'rural'

    Returns:
        float: Estimated range in kilometers
    """
    # Base ranges (SF12, 20dBm, line of sight)
    base_ranges = {
        "urban": 2,  # Lots of obstacles
        "suburban": 5,  # Some obstacles
        "rural": 10,  # Open field
    }

    base_range = base_ranges.get(environment, 5)

    # SF scaling (SF7 = 1x, SF12 = 4x range)
    sf_scale = 2 ** ((spreading_factor - 7) / 3)

    # Power scaling (rough approximation)
    power_scale = 10 ** ((tx_power - 20) / 40)

    estimated_range = base_range * sf_scale * power_scale

    return estimated_range
