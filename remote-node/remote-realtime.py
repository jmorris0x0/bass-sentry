import pyaudio
import numpy as np
from scipy.signal import butter, lfilter
import time
import logging
from telemetry_sender import TelemetrySender

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bandpass filter
def bandpass_filter(data, lowcut=15.0, highcut=100.0, fs=44100, order=5):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    y = lfilter(b, a, data)
    return y

# Calculate RMS
def rms(data):
    return np.sqrt(np.mean(data**2))

# Convert RMS to dB
def rms_to_db(rms_val, reference):
    if rms_val == 0:
        return -np.inf
    return 20 * np.log10(rms_val / reference)

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
SENDING_RATE = 2  # Twice per second
CHUNK = int(RATE / SENDING_RATE)  # Adjusted to match sending rate

def main():
    p = pyaudio.PyAudio()
    telemetry = TelemetrySender(topic_suffix="remote_node")
    
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print("Recording and processing...")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            np_data = np.frombuffer(data, dtype=np.int16).astype(float)
            np_data_normalized = np_data / np.max(np.abs(np_data))

            filtered_data = bandpass_filter(np_data_normalized)
            filtered_data = filtered_data / np.max(np.abs(filtered_data))
            filtered_data = filtered_data - np.mean(filtered_data)
            
            # Compute RMS and convert to dB
            rms_val = rms(filtered_data)
            db_val = rms_to_db(rms_val, reference=1.0)
            
            print(f"RMS value: {rms_val}")
            print(f"dBFS: {db_val:.2f}")
            
            # Send data
            json_data = {
                "station_id": telemetry.unit_name,
                "timestamp": time.time_ns(),
                #"rms_value": rms_val,  
                "15-100Hz": db_val  
            }
            telemetry.send_data(json_data)
            time.sleep(1/SENDING_RATE)

    except KeyboardInterrupt:
        logger.info("Stopping recording and data transmission.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        telemetry.stop()

if __name__ == "__main__":
    main()
