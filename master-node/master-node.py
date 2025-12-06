#!/usr/bin/env python

import json
import logging
import os
import time

from data_manager import DataManager

logging.basicConfig(
    level=logging.DEBUG,
    format="%(name)s - %(levelname)s - %(message)s - Line %(lineno)d",
)
logger = logging.getLogger(__name__)


def load_transport_config():
    """
    Load transport configuration from file if available.

    Checks for BASS_SENTRY_TRANSPORT_CONFIG environment variable or
    default config file path.

    Returns:
        dict or None: Transport configuration, or None for legacy MQTT
    """
    config_path = os.environ.get("BASS_SENTRY_TRANSPORT_CONFIG")

    if config_path and os.path.exists(config_path):
        logger.info(f"Loading transport config from: {config_path}")
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                return config.get("transport")
        except Exception as e:
            logger.error(f"Failed to load transport config: {e}")

    return None


def main():
    logger.info("Starting master node...")

    # Load transport config (optional)
    transport_config = load_transport_config()

    data_manager = DataManager(
        influx_url=os.environ.get("INFLUXDB_HOST", "http://influxdb:8086"),
        influx_token=os.environ.get("DOCKER_INFLUXDB_INIT_ADMIN_TOKEN", ""),
        influx_bucket=os.environ.get("DOCKER_INFLUXDB_INIT_BUCKET"),
        influx_org=os.environ.get("DOCKER_INFLUXDB_INIT_ORG"),
        mqtt_host="mosquitto",  # Legacy MQTT (used if transport_config is None)
        mqtt_port=1883,
        transport_config=transport_config,
    )

    data_manager.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        data_manager.mqtt_loop_stop()
        logger.info("Exiting master node...")


if __name__ == "__main__":
    main()
