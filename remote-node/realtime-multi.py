import multiprocessing
import pyaudio
import numpy as np
from scipy.signal import butter, lfilter
import time
import logging
from telemetry_sender import TelemetrySender
import ntplib
from time import ctime


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



# pyaudio.paInt16: 16-bit signed integer samples 
# pyaudio.paInt24: 24-bit signed integer samples 
# pyaudio.paInt32: 32-bit signed integer samples 

FORMAT = pyaudio.paInt16 # 16 bit audio
CHANNELS = 1
RATE = 44100
SENDING_RATE = 2
CHUNK = int(RATE / SENDING_RATE)


# Calculate RMS
def rms(data):
    if not isinstance(data, np.ndarray):
        data = np.array(data, dtype=float)
    return np.sqrt(np.mean(data**2))


# Convert RMS to dB
def rms_to_db(rms_val, bit_depth=16):
    if rms_val == 0:
        return -np.inf

    # Set reference value based on bit depth
    reference = {
        16: 2**15,  # for 16-bit audio
        24: 2**23,  # for 24-bit audio
        32: 2**31   # for 32-bit audio
    }.get(bit_depth, 2**15)  # Default to 16-bit if bit_depth is not recognized

    return 20 * np.log10(rms_val / reference)


def get_ntp_offset(ntp_server='pool.ntp.org'):
    c = ntplib.NTPClient()
    response = c.request(ntp_server, version=3)
    return response.offset


def recorder(data_queue):
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    ntp_offset = get_ntp_offset()
    logger.info(f'NTP offset: {ntp_offset * 1000:.3f} milliseconds')
    initial_time = time.time_ns() + int(ntp_offset * 1e9)
    samples_recorded = 0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            timestamp = initial_time + int((samples_recorded / RATE) * 1e9)
            data_queue.put((data, timestamp))
            samples_recorded += CHUNK
    except KeyboardInterrupt:
        stream.stop_stream()
        stream.close()
        p.terminate()


def sender(data_queue):
    telemetry = TelemetrySender(topic_suffix="remote_node")
    try:
        while True:
            data, timestamp = data_queue.get()
            np_data = np.frombuffer(data, dtype=np.int16).astype(float)
             
            rms_val = rms(np_data)
            db_val = rms_to_db(rms_val)

            json_data = {
                "station_id": telemetry.unit_name,
                "timestamp": timestamp,
                "15-100Hz": db_val  
            }
            telemetry.send_data(json_data)
    except KeyboardInterrupt:
        telemetry.stop()

if __name__ == "__main__":
    data_queue = multiprocessing.Queue()

    recorder_process = multiprocessing.Process(target=recorder, args=(data_queue,))
    sender_process = multiprocessing.Process(target=sender, args=(data_queue,))

    recorder_process.start()
    sender_process.start()

    recorder_process.join()
    sender_process.join()

