import argparse
import json
import logging
import multiprocessing
import signal
import sys
import time
from functools import partial
import functools

from pprint import pprint
import numpy as np
import ntplib
import sounddevice as sd
from scipy.signal import fftconvolve
from telemetry_sender import TelemetrySender
from processors import SignalProcessor


default_device_info = sd.query_devices(kind="input")
subtype = default_device_info.get('subtype', 'PCM_16')
if 'PCM' in subtype:
    BIT_DEPTH = int(''.join(filter(str.isdigit, subtype)))
else:
    BIT_DEPTH = 16  # Default to 16 if subtype is not PCM

DATA_TYPE_MAPPING = {
    8: np.int8,
    16: np.int16,
    32: np.int32,
    64: np.int64,
}
FORMAT = DATA_TYPE_MAPPING[BIT_DEPTH]
TP_FACTORS = {
    'ns': 1e9,
    'us': 1e6,
    'ms': 1e3,
    's': 1
}
TIME_PRECISION = 'ns'
TP_FACTOR = TP_FACTORS[TIME_PRECISION]
RATE = int(default_device_info["default_samplerate"])
CHANNELS = 1
SENDING_RATE = 2  # Hz
CHUNK = int(RATE / SENDING_RATE)


def setup_logging():
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    return logger


def signal_handler(recorder_process, sender_process, sig, frame):
    logger = setup_logging()
    logger.info("Received signal to terminate.")
    recorder_process.terminate()
    sender_process.terminate()
    recorder_process.join()
    sender_process.join()
    sys.exit(0)


def get_ntp_offset(ntp_server="pool.ntp.org"):
    logger = setup_logging()
    try:
        c = ntplib.NTPClient()
        response = c.request(ntp_server, version=3)
        return response.offset
    except Exception as e:
        logger.error(f"Failed to get NTP offset: {e}")
        return 0


def callback(
    indata,
    frames,
    time,
    status,
    data_queue,
    initial_time,
    ns_between_messages,
    sample_counter,
):
    logger = setup_logging()
    if status:
        if status & sd.CallbackFlags.input_overflow:
            logger.error(
                "Input overflow - buffer may be too small or system too slow, data may be lost!"
            )
        else:
            logger.warning(status)

    timestamp = initial_time + sample_counter.value * ns_between_messages
    logger.debug(
        f"ns_between_messages: {ns_between_messages}, sample_counter: {sample_counter.value}, timestamp: {timestamp}"
    )
    data_queue.put((indata.copy(), timestamp))
    sample_counter.value += 1


def recorder(data_queue, sample_counter):
    logger = setup_logging()
    ntp_offset = get_ntp_offset()
    initial_time = int((time.time_ns() + ntp_offset * TP_FACTOR))
    ns_between_messages = int(TP_FACTOR / SENDING_RATE)
    callback_with_queue = partial(
        callback,
        data_queue=data_queue,
        initial_time=initial_time,
        ns_between_messages=ns_between_messages,
        sample_counter=sample_counter,
    )

    stream = sd.InputStream(
        callback=callback_with_queue,
        channels=CHANNELS,
        dtype=FORMAT,
        samplerate=RATE,
        blocksize=CHUNK,
        finished_callback=lambda: logger.info("Stream finished"),
    )
    try:
        with stream:
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Recording stopped by user")
        return


def sender(data_queue, config):
    logger = setup_logging()
    telemetry = TelemetrySender(topic_suffix="remote_node")
    prev_timestamp = None

    # Create an instance of SignalProcessor
    signal_processor = SignalProcessor(config)

    # Extract location from the config
    location = config.get("location", "")

    try:
        while True:
            try:
                data, timestamp = data_queue.get(timeout=1)
            except multiprocessing.queues.Empty:
                continue

            current_timestamp = int(time.time() * TP_FACTOR)
            drift = current_timestamp - timestamp
            logger.debug(f"Timestamp drift: {drift} ns")

            if prev_timestamp is not None:
                diff = timestamp - prev_timestamp
                logger.debug(f"Timestamp diff: {diff} ns")

            prev_timestamp = timestamp

            np_data = np.frombuffer(data, dtype=np.int16).astype(float)

            audio_data = {
                "data_type": "audio_chunk",
                "data": np_data.tolist(),
                "metadata": {
                    "sample_rate": RATE,
                    "bit_depth": BIT_DEPTH,
                    "location": location,  # Include location in metadata
                },
                "timestamp": timestamp,
                "time_precision": TIME_PRECISION,
            }

            processed_data_list = signal_processor.process(audio_data)

            for processed_data in processed_data_list:
                pprint(processed_data)
                json_data = {
                    "data": processed_data["data"],
                    "station_id": telemetry.unit_name,
                    "data_type": processed_data["data_type"],
                    "metadata": {
                        "units": processed_data["metadata"]["units"],
                        "location": location,  # Include location in metadata
                    },
                    "timestamp": processed_data["timestamp"],
                    "time_precision": TIME_PRECISION,
                }

                telemetry.send_data(json_data)

    except KeyboardInterrupt:
        telemetry.stop()
    except Exception as e:
        logger.error(f"Unexpected error in sender: {e}")
        telemetry.stop()


def main():
    parser = argparse.ArgumentParser(description="Process signals.")
    parser.add_argument("config", type=str, help="Path to the JSON configuration file")
    args = parser.parse_args()

    # Read the JSON configuration file
    with open(args.config, "r") as f:
        config = json.load(f)

    data_queue = multiprocessing.Queue()
    sample_counter = multiprocessing.Value("i", 0)

    recorder_process = multiprocessing.Process(
        target=recorder, args=(data_queue, sample_counter)
    )

    sender_process = multiprocessing.Process(target=sender, args=(data_queue, config))

    recorder_process.start()
    sender_process.start()

    handler = functools.partial(signal_handler, recorder_process, sender_process)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    try:
        recorder_process.join()
        sender_process.join()
    except KeyboardInterrupt:
        logger = setup_logging()
        logger.info("Keyboard interrupt received, terminating processes...")
        signal_handler(recorder_process, sender_process, None, None)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
