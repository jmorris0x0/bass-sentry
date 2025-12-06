import argparse
import functools
import json
import logging
import multiprocessing
import platform
import signal
import sys
import time
from functools import partial
from pprint import pprint, pformat

import numpy as np
import ntplib
import sounddevice as sd
from scipy.signal import fftconvolve

# Add parent directory to path for common imports
sys.path.insert(0, "/Users/jonathan/code/bass-sentry")
from common.time_sync import TimeSync

from processors import SignalProcessor
from telemetry_sender import TelemetrySender


def get_input_device():
    devices = sd.query_devices()
    # logger.info("Found audio devices:\n{}".format(devices))

    if platform.system() == "Linux":  # Assume Raspberry Pi
        for i, d in enumerate(devices):
            # logger.debug(f"Device {i}: {d['name']}")
            if "USB Audio CODEC" in d["name"]:
                # logger.debug(f"Found USB Audio CODEC at device {i}.")
                return d
        # logger.debug("USB Audio CODEC not found. Using default input device.")
        return sd.query_devices(kind="input")  # Use the default device
    else:  # Use the default device
        # logger.debug("Not on Linux, using default input device.")
        return sd.query_devices(kind="input")


device_info = get_input_device()

BIT_DEPTH = 16  # Default to 16 if subtype is not PCM

DATA_TYPE_MAPPING = {
    8: np.int8,
    16: np.int16,
    32: np.int32,
    64: np.int64,
}
FORMAT = DATA_TYPE_MAPPING[BIT_DEPTH]
TP_FACTORS = {"ns": 1e9, "us": 1e6, "ms": 1e3, "s": 1}
TIME_PRECISION = "ns"
TP_FACTOR = TP_FACTORS[TIME_PRECISION]
RATE = int(device_info["default_samplerate"])
INPUT_DEVICE = int(device_info["index"])
CHANNELS = 1
SENDING_RATE = 2  # Hz
CHUNK = int(RATE / SENDING_RATE)
# Maximum queue size to prevent memory exhaustion (max ~30 seconds of buffering)
MAX_QUEUE_SIZE = 60  # 60 chunks = 30 seconds at 2 Hz


def setup_logging():
    # Define your date format
    date_format = "%Y-%m-%d %H:%M:%S %Z"  # This includes timezone information

    # Include the asctime field in your format string and set the datefmt parameter
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s - Line %(lineno)d",
        datefmt=date_format,
    )
    logger = logging.getLogger(__name__)

    return logger


def signal_handler(recorder_process, sender_process, time_sync_manager, sig, frame):
    logger = setup_logging()
    logger.info("Received signal to terminate.")

    # Stop time sync first
    if time_sync_manager:
        time_sync_manager.stop()

    # Terminate processes
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
    time_sync,
):
    logger = setup_logging()

    if status:
        status_flags = str(status).replace("CallbackFlags.", "") if status else "None"
        logger.warning(f"Status flags: {status_flags}")
        # Check if status.input_overflow is set
        if status.input_overflow:
            logger.warning(
                "Input overflow - buffer may be too small or system too slow, data may be lost!"
            )

    # Check queue size to prevent memory exhaustion
    if data_queue.qsize() >= MAX_QUEUE_SIZE:
        logger.error(
            f"Queue full ({data_queue.qsize()} items), dropping audio chunk! "
            f"Sender process may be too slow or stalled."
        )
        # Still increment counter to maintain timestamp consistency
        sample_counter.value += 1
        return

    # Calculate timestamp with drift compensation
    base_timestamp = initial_time + sample_counter.value * ns_between_messages

    # Apply time sync offset (converted to nanoseconds)
    offset_ns = int(time_sync.get_offset() * TP_FACTOR)
    timestamp = base_timestamp + offset_ns

    logger.debug(
        f"ns_between_messages: {ns_between_messages}, sample_counter: {sample_counter.value}, "
        f"timestamp: {timestamp}, offset: {offset_ns}ns"
    )
    data_queue.put((indata.copy(), timestamp))
    sample_counter.value += 1


def recorder(data_queue, sample_counter, time_sync_manager):
    logger = setup_logging()

    # Get initial offset from time sync
    ntp_offset = time_sync_manager.get_offset()
    initial_time = int((time.time_ns() + ntp_offset * TP_FACTOR))
    ns_between_messages = int(TP_FACTOR / SENDING_RATE)

    callback_with_queue = partial(
        callback,
        data_queue=data_queue,
        initial_time=initial_time,
        ns_between_messages=ns_between_messages,
        sample_counter=sample_counter,
        time_sync=time_sync_manager,
    )

    stream = sd.InputStream(
        device=INPUT_DEVICE,
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

                # Periodically log time sync status
                if sample_counter.value % (SENDING_RATE * 60) == 0:  # Every minute
                    stats = time_sync_manager.get_stats()
                    logger.debug(
                        f"Time sync: offset={stats['last_offset_seconds']*1000:.1f}ms, "
                        f"drift={stats['drift_ppm']:.2f}ppm"
                    )
    except KeyboardInterrupt:
        logger.info("Recording stopped by user")
        return


def sender(data_queue, config):
    logger = setup_logging()

    # Extract transport configuration (if provided)
    transport_config = config.get("transport", None)

    telemetry = TelemetrySender(
        topic_suffix="remote_node", transport_config=transport_config
    )
    prev_timestamp = None
    dropped_chunks = 0
    total_chunks = 0

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

            total_chunks += 1

            # Monitor queue health
            queue_size = data_queue.qsize()
            if queue_size > MAX_QUEUE_SIZE * 0.8:
                logger.warning(
                    f"Queue is {queue_size}/{MAX_QUEUE_SIZE} full ({queue_size/MAX_QUEUE_SIZE*100:.1f}%)"
                )

            current_timestamp = int(time.time() * TP_FACTOR)
            drift = current_timestamp - timestamp
            logger.debug(f"Timestamp drift: {drift} ns")

            # Detect dropped chunks by checking timestamp continuity
            if prev_timestamp is not None:
                diff = timestamp - prev_timestamp
                expected_diff = int(TP_FACTOR / SENDING_RATE)
                if abs(diff - expected_diff) > expected_diff * 0.1:
                    dropped_chunks += 1
                    logger.error(
                        f"Timestamp discontinuity detected! Expected {expected_diff} ns, "
                        f"got {diff} ns. Chunks may have been dropped. "
                        f"Total dropped: {dropped_chunks}/{total_chunks}"
                    )
                logger.debug(f"Timestamp diff: {diff} ns")

            prev_timestamp = timestamp

            np_data = np.frombuffer(data, dtype=np.int16).astype(float)

            audio_data = {
                "data_type": "audio_chunk",
                "data": np_data.tolist(),
                "timestamp": timestamp,
                "time_precision": TIME_PRECISION,
                "metadata": {
                    "sample_rate": RATE,
                    "bit_depth": BIT_DEPTH,
                    "location": location,
                },
            }

            processed_data_list = signal_processor.process(audio_data)

            for processed_data in processed_data_list:
                processed_data["station_id"] = telemetry.unit_name
                if type(processed_data["data"]) == np.ndarray:
                    processed_data["data"] = processed_data["data"].tolist()
                logger.debug("Processed data: %s", pformat(processed_data))

                telemetry.send_data(processed_data)

    except KeyboardInterrupt:
        telemetry.stop()
    except Exception as e:
        logger.error(f"Unexpected error in sender: {e}")
        telemetry.stop()


def main():
    parser = argparse.ArgumentParser(description="Process signals.")
    parser.add_argument("config", type=str, help="Path to the JSON configuration file")
    parser.add_argument(
        "--ntp-server",
        type=str,
        default="pool.ntp.org",
        help="NTP server for time sync (default: pool.ntp.org)",
    )
    parser.add_argument(
        "--sync-interval",
        type=int,
        default=300,
        help="NTP sync interval in seconds (default: 300)",
    )
    args = parser.parse_args()

    logger = setup_logging()

    # Read the JSON configuration file
    with open(args.config, "r") as f:
        config = json.load(f)

    # Initialize continuous time synchronization
    logger.info(f"Starting time sync with server: {args.ntp_server}")
    time_sync_manager = TimeSync(
        ntp_server=args.ntp_server, sync_interval=args.sync_interval
    )
    time_sync_manager.start()

    # Use bounded queue to prevent memory exhaustion
    data_queue = multiprocessing.Queue(maxsize=MAX_QUEUE_SIZE)
    sample_counter = multiprocessing.Value("i", 0)

    # Initialize processes with daemon=True
    recorder_process = multiprocessing.Process(
        target=recorder, args=(data_queue, sample_counter, time_sync_manager)
    )
    recorder_process.daemon = True  # Ensures it will close with main process

    sender_process = multiprocessing.Process(target=sender, args=(data_queue, config))
    sender_process.daemon = True  # Ensures it will close with main process

    # Start both processes
    recorder_process.start()
    sender_process.start()

    # Set up signal handler
    handler = functools.partial(
        signal_handler, recorder_process, sender_process, time_sync_manager
    )
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    try:
        # Use try-finally to ensure cleanup
        recorder_process.join()
        sender_process.join()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, terminating processes...")
        signal_handler(recorder_process, sender_process, time_sync_manager, None, None)
    finally:
        # Stop time sync
        time_sync_manager.stop()

        # Ensure all processes are terminated
        if recorder_process.is_alive():
            recorder_process.terminate()
        if sender_process.is_alive():
            sender_process.terminate()

        recorder_process.join()
        sender_process.join()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
