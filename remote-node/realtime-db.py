from datetime import datetime
from time import ctime
import logging
import multiprocessing
import numpy as np
import signal
import sys
import time
from functools import partial

import ntplib
import sounddevice as sd
from telemetry_sender import TelemetrySender

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

default_device_info = sd.query_devices(kind="input")
RATE = int(default_device_info["default_samplerate"])
FORMAT = np.int16  # 16 bit audio
CHANNELS = 1
SENDING_RATE = 2
CHUNK = int(RATE / SENDING_RATE)


def signal_handler(sig, frame):
    logger.info("Received signal to terminate.")
    recorder_process.terminate()
    sender_process.terminate()
    recorder_process.join()
    sender_process.join()
    sys.exit(0)


def rms(data):
    return np.sqrt(np.mean(data**2))


def rms_to_db(rms_val, bit_depth=16):
    if rms_val == 0:
        return -np.inf
    reference = 2 ** (bit_depth - 1)
    return 20 * np.log10(rms_val / reference)


def dbfs_to_dbspl(dbfs_val, conversion_factor):
    return dbfs_val + conversion_factor


def get_ntp_offset(ntp_server="pool.ntp.org"):
    try:
        c = ntplib.NTPClient()
        response = c.request(ntp_server, version=3)
        return response.offset
    except Exception as e:
        logger.error(f"Failed to get NTP offset: {e}")
        return 0  # return a default value or handle the error as appropriate


def callback(indata, frames, time, status, data_queue, initial_time, ns_per_frame, sample_counter):
    if status:
        if status & sd.CallbackFlags.input_overflow:
            logger.error('Input overflow - buffer may be too small or system too slow, data may be lost!')
        else:
            logger.warning(status)
    
    timestamp = initial_time + sample_counter.value * ns_per_frame
    data_queue.put((indata.copy(), timestamp))
    sample_counter.value += 1


def recorder(data_queue, sample_counter):
    ntp_offset = get_ntp_offset()
    initial_time = int((time.time_ns() + ntp_offset * 1e9))
    ns_per_frame = int(1e9 / RATE)
    callback_with_queue = partial(callback, data_queue=data_queue, initial_time=initial_time, ns_per_frame=ns_per_frame, sample_counter=sample_counter)

    stream = sd.InputStream(callback=callback_with_queue, channels=CHANNELS, dtype=FORMAT, samplerate=RATE, blocksize=CHUNK, finished_callback=lambda: print("Stream finished"))
    try:
        with stream:
            while True:
                time.sleep(0.1)  # Keep the main thread alive
    except KeyboardInterrupt:
        logger.info('Recording stopped by user')
        return


def sender(data_queue):
    telemetry = TelemetrySender(topic_suffix="remote_node")
    try:
        while True:
            try:
                data, timestamp = data_queue.get(
                    timeout=1
                )  # Timeout to handle empty queue
            except multiprocessing.queues.Empty:
                continue

            np_data = np.frombuffer(data, dtype=np.int16).astype(float)
            rms_val = rms(np_data)
            db_val = rms_to_db(rms_val)

            json_data = {
                "station_id": telemetry.unit_name,
                "timestamp": timestamp,
                "15-100Hz": db_val,
            }
            telemetry.send_data(json_data)
    except KeyboardInterrupt:
        telemetry.stop()
    except Exception as e:
        logger.error(f"Unexpected error in sender: {e}")
        telemetry.stop()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    data_queue = multiprocessing.Queue()
    sample_counter = multiprocessing.Value('i', 0)  # 'i' indicates a signed int

    recorder_process = multiprocessing.Process(target=recorder, args=(data_queue, sample_counter))
    sender_process = multiprocessing.Process(target=sender, args=(data_queue,))

    try:
        recorder_process.start()
        sender_process.start()

        recorder_process.join()
        sender_process.join()
    except KeyboardInterrupt:
        logger.info("Terminating due to Ctrl+C")
    finally:
        recorder_process.terminate()
        sender_process.terminate()
        recorder_process.join()
        sender_process.join()
