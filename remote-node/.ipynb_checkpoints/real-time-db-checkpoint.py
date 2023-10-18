import pyaudio
import numpy as np
from scipy.signal import butter, lfilter
import matplotlib.pyplot as plt

# Bandpass filter
def bandpass_filter(data, lowcut=15.0, highcut=80.0, fs=44100, order=5):
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

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
RECORD_SECONDS = 20

p = pyaudio.PyAudio()

stream = p.open(format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK)

print("Recording and processing...")


for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
    data = stream.read(CHUNK)
    np_data = np.frombuffer(data, dtype=np.int16).astype(float)
    
    # Normalize the data to be between -1 and 1
    np_data = np_data / np.max(np.abs(np_data))
    
    # Apply the bandpass filter
    filtered_data = bandpass_filter(np_data, fs=RATE)
    
    # Plot the filtered data
    plt.figure(figsize=(10, 4))
    plt.plot(filtered_data)
    plt.title("Filtered Data")
    plt.grid(True)
    plt.show()

    # Compute RMS and convert to dB
    rms_val = rms(filtered_data)
    db_val = rms_to_db(rms_val, reference=1.0)
    
    print(f"RMS value: {rms_val}")
    print(f"dBFS: {db_val:.2f}")

stream.stop_stream()
stream.close()
p.terminate()
