"""
Pluggable Transport Layer for Bass Sentry

Abstracts communication layer to support multiple transports:
- MQTT (default, WiFi)
- LoRa (long-range, 2-10km)
- HTTP (cellular/internet)
- Serial (direct connection)

Usage:
    # Remote node
    transport = get_transport(config)
    transport.send('remote_node/pi-1', audio_chunk_data)

    # Master node
    transport = get_transport(config)
    transport.subscribe('remote_node/#', callback=process_data)
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class TransportType(Enum):
    """Available transport types."""

    MQTT = "mqtt"
    LORA = "lora"
    HTTP = "http"
    SERIAL = "serial"


class Transport(ABC):
    """
    Abstract base class for all transports.

    All transports must implement:
    - send(): Send data to a topic/destination
    - subscribe(): Register callback for incoming data
    - connect(): Establish connection
    - disconnect(): Clean shutdown
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize transport.

        Args:
            config: Transport-specific configuration
        """
        self.config = config
        self.connected = False
        self.callbacks = {}  # topic -> callback mapping

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection.

        Returns:
            bool: True if successful
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Clean shutdown of transport."""
        pass

    @abstractmethod
    def send(self, topic: str, data: Dict[str, Any], **kwargs) -> bool:
        """
        Send data to a topic/destination.

        Args:
            topic: Destination identifier (e.g., 'remote_node/pi-1')
            data: Data to send (must be JSON-serializable)
            **kwargs: Transport-specific options

        Returns:
            bool: True if sent successfully
        """
        pass

    @abstractmethod
    def subscribe(self, topic: str, callback: Callable[[str, Dict], None]):
        """
        Subscribe to topic and register callback.

        Args:
            topic: Topic pattern to subscribe (e.g., 'remote_node/#')
            callback: Function called with (topic, data) when message arrives
        """
        pass

    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self.connected


class TransportConfig:
    """Configuration for transport layer."""

    def __init__(self, transport_type: str = "mqtt", **kwargs):
        """
        Args:
            transport_type: Type of transport ('mqtt', 'lora', 'http', 'serial')
            **kwargs: Transport-specific configuration
        """
        self.transport_type = TransportType(transport_type)
        self.config = kwargs

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "TransportConfig":
        """Create from dictionary (e.g., loaded from JSON)."""
        transport_type = config.get("type", "mqtt")
        transport_config = config.get(transport_type, {})
        return cls(transport_type=transport_type, **transport_config)

    @classmethod
    def from_file(cls, path: str) -> "TransportConfig":
        """Load configuration from JSON file."""
        import json

        with open(path, "r") as f:
            config = json.load(f)
        return cls.from_dict(config.get("transport", {}))


def get_transport(config: TransportConfig) -> Transport:
    """
    Factory function to create transport instance.

    Args:
        config: TransportConfig instance

    Returns:
        Transport: Initialized transport instance

    Raises:
        ValueError: If transport type not supported
    """
    if config.transport_type == TransportType.MQTT:
        from common.transport_mqtt import MQTTTransport

        return MQTTTransport(config.config)

    elif config.transport_type == TransportType.LORA:
        from common.transport_lora import LoRaTransport

        return LoRaTransport(config.config)

    elif config.transport_type == TransportType.HTTP:
        from common.transport_http import HTTPTransport

        return HTTPTransport(config.config)

    elif config.transport_type == TransportType.SERIAL:
        from common.transport_serial import SerialTransport

        return SerialTransport(config.config)

    else:
        raise ValueError(f"Unsupported transport type: {config.transport_type}")


# Convenience function for common use case
def create_transport(transport_type: str = "mqtt", **kwargs) -> Transport:
    """
    Quick transport creation.

    Args:
        transport_type: 'mqtt', 'lora', 'http', or 'serial'
        **kwargs: Transport-specific configuration

    Returns:
        Transport: Initialized transport instance

    Example:
        transport = create_transport('mqtt', broker='localhost', port=1883)
        transport = create_transport('lora', frequency=915, spreading_factor=7)
    """
    config = TransportConfig(transport_type=transport_type, **kwargs)
    return get_transport(config)
