#!/usr/bin/env python

import logging
import os
import time
from data_manager import DataManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting master node...")

    data_manager = DataManager(
        influx_url=os.environ.get("INFLUXDB_HOST", "http://influxdb:8086"),
        influx_token=os.environ.get("DOCKER_INFLUXDB_INIT_ADMIN_TOKEN", ""),
        influx_bucket=os.environ.get("DOCKER_INFLUXDB_INIT_BUCKET"),
        influx_org=os.environ.get("DOCKER_INFLUXDB_INIT_ORG"),
        mqtt_host="mosquitto",
        mqtt_port=1883,
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
