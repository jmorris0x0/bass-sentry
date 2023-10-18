# Needs:
# pip install paho-mqtt zeroconf

import logging
import time
from telemetry_sender import TelemetrySender

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    telemetry = TelemetrySender(topic_suffix="remote_node")
    try:
        while True:
            json_data = {
                "station_id": telemetry.unit_name,
                "timestamp": time.time_ns(),
                "frequency_1": 1,  # Sample data 1
                "frequency_2": 2  # Sample data 2
            }
            telemetry.send_data(json_data)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping data transmission.")
    finally:
        telemetry.stop()

if __name__ == "__main__":
    main()
