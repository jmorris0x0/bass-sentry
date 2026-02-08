"""Tests for transport layer."""

import os
import pytest
import sys
import time
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from transport import TransportConfig, get_transport, TransportType
from transport_mqtt import MQTTTransport


class TestMQTTTransport:
    """Test MQTT transport implementation."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        transport = MQTTTransport({})
        assert transport.broker == "localhost"
        assert transport.port == 1883
        assert transport.qos == 1
        assert not transport.connected

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = {
            "broker": "mqtt.example.com",
            "port": 8883,
            "qos": 2,
            "username": "user",
            "password": "pass",
        }
        transport = MQTTTransport(config)
        assert transport.broker == "mqtt.example.com"
        assert transport.port == 8883
        assert transport.qos == 2

    @patch("transport_mqtt.mqtt.Client")
    def test_connect_success(self, mock_client_class):
        """Test successful connection."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({"broker": "localhost"})

        # Simulate successful connection callback
        def trigger_connect(*args):
            transport._on_connect(mock_client, None, None, 0)

        mock_client.connect.side_effect = trigger_connect

        result = transport.connect()

        assert result is True
        assert transport.connected is True
        mock_client.loop_start.assert_called_once()

    @patch("transport_mqtt.mqtt.Client")
    def test_connect_timeout(self, mock_client_class):
        """Test connection timeout."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({"broker": "localhost"})
        # Don't trigger on_connect - simulates timeout

        result = transport.connect()

        assert result is False
        assert transport.connected is False

    @patch("transport_mqtt.mqtt.Client")
    def test_send_when_disconnected(self, mock_client_class):
        """Test send fails gracefully when disconnected."""
        transport = MQTTTransport({})
        transport.connected = False

        result = transport.send("test/topic", {"data": "test"})

        assert result is False
        assert transport.stats["messages_failed"] == 1

    @patch("transport_mqtt.mqtt.Client")
    def test_send_success(self, mock_client_class):
        """Test successful send."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.publish.return_value = MagicMock(rc=0)  # MQTT_ERR_SUCCESS

        transport = MQTTTransport({})
        transport.connected = True
        transport.client = mock_client

        result = transport.send("test/topic", {"data": "test"})

        assert result is True
        assert transport.stats["messages_sent"] == 1

    @patch("transport_mqtt.mqtt.Client")
    def test_subscribe(self, mock_client_class):
        """Test subscription."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({})
        callback = Mock()

        transport.subscribe("test/topic", callback)

        assert "test/topic" in transport.callbacks
        assert transport.callbacks["test/topic"] == callback
        mock_client.subscribe.assert_called_once()

    @patch("transport_mqtt.mqtt.Client")
    def test_resubscribe_on_reconnect(self, mock_client_class):
        """Test that subscriptions are restored on reconnect."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({})

        # Subscribe to topics
        callback = Mock()
        transport.callbacks["test/topic1"] = callback
        transport.callbacks["test/topic2"] = callback

        # Simulate reconnect
        transport._on_connect(mock_client, None, {"session_present": False}, 0)

        # Verify resubscription
        assert mock_client.subscribe.call_count == 2

    @patch("transport_mqtt.mqtt.Client")
    def test_message_callback(self, mock_client_class):
        """Test message callback dispatching."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({})
        callback = Mock()
        transport.callbacks["test/#"] = callback

        # Create mock message
        mock_msg = MagicMock()
        mock_msg.topic = "test/subtopic"
        mock_msg.payload = b'{"key": "value"}'

        transport._on_message(mock_client, None, mock_msg)

        callback.assert_called_once()
        assert transport.stats["messages_received"] == 1

    @patch("transport_mqtt.mqtt.Client")
    def test_disconnect(self, mock_client_class):
        """Test disconnect."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({})
        transport.connected = True

        transport.disconnect()

        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()
        assert transport.connected is False

    def test_get_stats(self):
        """Test stats retrieval."""
        transport = MQTTTransport({})
        transport.stats["messages_sent"] = 10
        transport.stats["messages_failed"] = 2
        transport.connected = True

        stats = transport.get_stats()

        assert stats["messages_sent"] == 10
        assert stats["messages_failed"] == 2
        assert stats["connected"] is True


class TestTransportConfig:
    """Test transport configuration."""

    def test_from_dict_mqtt(self):
        """Test creating MQTT config from dict."""
        config = TransportConfig.from_dict(
            {"type": "mqtt", "mqtt": {"broker": "localhost", "port": 1883}}
        )
        assert config.transport_type == TransportType.MQTT
        assert config.config["broker"] == "localhost"

    def test_from_dict_default(self):
        """Test default transport type."""
        config = TransportConfig.from_dict({})
        assert config.transport_type == TransportType.MQTT

    def test_from_dict_lora(self):
        """Test LoRa config from dict."""
        config = TransportConfig.from_dict(
            {"type": "lora", "lora": {"frequency": 915, "spreading_factor": 7}}
        )
        assert config.transport_type == TransportType.LORA
        assert config.config["frequency"] == 915

    def test_from_dict_http(self):
        """Test HTTP config from dict."""
        config = TransportConfig.from_dict(
            {"type": "http", "http": {"base_url": "https://api.example.com"}}
        )
        assert config.transport_type == TransportType.HTTP

    def test_from_dict_serial(self):
        """Test Serial config from dict."""
        config = TransportConfig.from_dict(
            {"type": "serial", "serial": {"port": "/dev/ttyUSB0", "baudrate": 115200}}
        )
        assert config.transport_type == TransportType.SERIAL


class TestGetTransport:
    """Test transport factory."""

    def test_get_mqtt_transport(self):
        """Test getting MQTT transport."""
        config = TransportConfig(transport_type="mqtt", broker="localhost")
        transport = get_transport(config)

        # Check by class name due to different import paths
        assert transport.__class__.__name__ == "MQTTTransport"
        assert transport.broker == "localhost"

    def test_invalid_transport_type(self):
        """Test invalid transport type raises error."""
        with pytest.raises(ValueError):
            config = TransportConfig(transport_type="invalid")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
