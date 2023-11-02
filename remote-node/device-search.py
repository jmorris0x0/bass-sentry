import platform
import logging

import sounddevice as sd


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_input_device():
    devices = sd.query_devices()
    logger.info("Found audio devices:\n{}".format(devices))

    if platform.system() == "Linux":  # Assume Raspberry Pi
        for i, d in enumerate(devices):
            logger.debug(f"Device {i}: {d['name']}")
            if "USB Audio CODEC" in d["name"]:
                logger.debug(f"Found USB Audio CODEC at device {i}.")
                return d
        logger.debug("USB Audio CODEC not found. Using default input device.")
        return sd.query_devices(kind="input")  # Use the default device
    else:  # Use the default device
        logger.debug("Not on Linux, using default input device.")
        return sd.query_devices(kind="input")

print(get_input_device())





