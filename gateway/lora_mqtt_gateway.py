#!/usr/bin/env python3
"""
LoRa to MQTT Gateway

Bridges LoRa remote nodes to MQTT master node.
Perfect for when master node runs on Mac/PC without LoRa hardware.

Architecture:
    Remote Nodes (LoRa) → Gateway Pi (LoRa HAT) → MQTT → Master Node (Mac/PC)

Hardware Requirements:
    - Raspberry Pi (any model, Pi Zero W is sufficient)
    - LoRa HAT (Dragino, RAK, or Adafruit)
    - WiFi or Ethernet connection to master node

Usage:
    python lora_mqtt_gateway.py --config gateway-config.json

    Or with command-line args:
    python lora_mqtt_gateway.py --lora-freq 915 --mqtt-broker 192.168.1.100
"""

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

# Add parent directory to path for common imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.transport import create_transport

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LoRaMQTTGateway:
    """
    Gateway that bridges LoRa and MQTT transports.

    Receives messages from LoRa remote nodes and forwards to MQTT master node.
    """

    def __init__(self, config):
        """
        Initialize gateway.

        Args:
            config: Dictionary with 'lora' and 'mqtt' transport configurations
        """
        self.config = config
        self.running = False

        # Statistics
        self.stats = {
            "lora_received": 0,
            "mqtt_sent": 0,
            "mqtt_failed": 0,
            "started_at": None,
        }

        # Create transports
        logger.info("Creating LoRa transport...")
        self.lora = self._create_lora_transport(config["lora"])

        logger.info("Creating MQTT transport...")
        self.mqtt = self._create_mqtt_transport(config["mqtt"])

    def _create_lora_transport(self, lora_config):
        """Create LoRa transport from config."""
        return create_transport("lora", **lora_config)

    def _create_mqtt_transport(self, mqtt_config):
        """Create MQTT transport from config."""
        return create_transport("mqtt", **mqtt_config)

    def start(self):
        """Start gateway operation."""
        logger.info("=" * 60)
        logger.info("Starting LoRa to MQTT Gateway")
        logger.info("=" * 60)

        # Connect LoRa
        logger.info("Connecting LoRa transport...")
        if not self.lora.connect():
            logger.error("Failed to connect LoRa transport")
            return False

        lora_stats = self.lora.get_stats()
        logger.info(
            f"LoRa connected: {lora_stats.get('spreading_factor', 'N/A')}SF, "
            f"{lora_stats.get('bandwidth_khz', 'N/A')}kHz, "
            f"{lora_stats.get('tx_power_dbm', 'N/A')}dBm"
        )

        # Connect MQTT
        logger.info("Connecting MQTT transport...")
        if not self.mqtt.connect():
            logger.error("Failed to connect MQTT transport")
            self.lora.disconnect()
            return False

        logger.info(f"MQTT connected to broker")

        # Subscribe to all LoRa topics
        logger.info("Subscribing to LoRa messages...")
        self.lora.subscribe("#", self._on_lora_message)

        self.running = True
        self.stats["started_at"] = time.time()

        logger.info("=" * 60)
        logger.info("Gateway running! Press Ctrl+C to stop")
        logger.info("=" * 60)

        return True

    def _on_lora_message(self, topic, data):
        """
        Callback when LoRa message received.

        Forwards message to MQTT.
        """
        self.stats["lora_received"] += 1

        logger.debug(f"LoRa received: {topic}")

        # Get LoRa signal quality
        lora_stats = self.lora.get_stats()
        rssi = lora_stats.get("rssi_last")
        snr = lora_stats.get("snr_last")

        if rssi is not None:
            logger.debug(f"  Signal: RSSI={rssi}dBm, SNR={snr}dB")

        # Forward to MQTT
        success = self.mqtt.send(topic, data)

        if success:
            self.stats["mqtt_sent"] += 1
        else:
            self.stats["mqtt_failed"] += 1
            logger.warning(f"Failed to forward message to MQTT: {topic}")

        # Log stats periodically
        if self.stats["lora_received"] % 100 == 0:
            self._log_stats()

    def _log_stats(self):
        """Log gateway statistics."""
        uptime = time.time() - self.stats["started_at"]
        logger.info(
            f"Gateway stats: {int(uptime)}s uptime, "
            f"LoRa RX: {self.stats['lora_received']}, "
            f"MQTT TX: {self.stats['mqtt_sent']}, "
            f"MQTT failed: {self.stats['mqtt_failed']}"
        )

    def stop(self):
        """Stop gateway operation."""
        logger.info("Stopping gateway...")
        self.running = False

        # Disconnect transports
        if self.lora:
            self.lora.disconnect()
        if self.mqtt:
            self.mqtt.disconnect()

        # Final stats
        self._log_stats()
        logger.info("Gateway stopped")

    def run(self):
        """Run gateway (blocking)."""
        if not self.start():
            logger.error("Failed to start gateway")
            sys.exit(1)

        # Run until interrupted
        try:
            while self.running:
                time.sleep(1)

                # Periodic stats logging
                if int(time.time() - self.stats["started_at"]) % 60 == 0:
                    self._log_stats()

        except KeyboardInterrupt:
            logger.info("\nKeyboard interrupt received")
        finally:
            self.stop()


def load_config(config_path):
    """Load configuration from JSON file."""
    try:
        with open(config_path, "r") as f:
            config = json.load(f)

        # Validate required sections
        if "lora" not in config or "mqtt" not in config:
            raise ValueError("Config must contain 'lora' and 'mqtt' sections")

        return config

    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="LoRa to MQTT Gateway")
    parser.add_argument("--config", type=str, help="Path to configuration JSON file")

    # LoRa options
    parser.add_argument("--lora-freq", type=int, help="LoRa frequency (915, 868, 433)")
    parser.add_argument(
        "--lora-sf", type=int, default=7, help="LoRa spreading factor (7-12)"
    )
    parser.add_argument(
        "--lora-power", type=int, default=20, help="LoRa TX power (5-23 dBm)"
    )
    parser.add_argument(
        "--lora-node-id", type=int, default=0, help="LoRa gateway node ID (default: 0)"
    )

    # MQTT options
    parser.add_argument("--mqtt-broker", type=str, help="MQTT broker address")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--mqtt-qos", type=int, default=1, help="MQTT QoS (0, 1, 2)")

    args = parser.parse_args()

    # Load config from file or build from command-line args
    if args.config:
        config = load_config(args.config)
    else:
        # Build config from command-line arguments
        if not args.lora_freq or not args.mqtt_broker:
            logger.error(
                "Either --config or both --lora-freq and --mqtt-broker are required"
            )
            parser.print_help()
            sys.exit(1)

        config = {
            "lora": {
                "frequency": args.lora_freq,
                "spreading_factor": args.lora_sf,
                "tx_power": args.lora_power,
                "node_id": args.lora_node_id,
                "gateway_id": 0,  # Gateway is always ID 0
            },
            "mqtt": {
                "broker": args.mqtt_broker,
                "port": args.mqtt_port,
                "qos": args.mqtt_qos,
            },
        }

    # Create and run gateway
    gateway = LoRaMQTTGateway(config)

    # Handle signals for clean shutdown
    def signal_handler(sig, frame):
        logger.info(f"\nReceived signal {sig}")
        gateway.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run
    gateway.run()


if __name__ == "__main__":
    main()
