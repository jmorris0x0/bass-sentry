import logging
import json
import numpy as np
import numpy as np
import ntplib
import sounddevice as sd
from scipy.signal import fftconvolve


class SignalProcessor:
    def __init__(self, config_file):
        self.steps = {}
        self.load_config(config_file)
        self.step_map = {
            "dbfs_measurement": DbfsMeasurement,
            "bandpass_ilter": BandpassFilter,
            "downsample": Downsample,
        }

    def load_config(self, config_file):
        with open(config_file, "r") as file:
            config = json.load(file)
            self.steps = config["steps"]

    def process(self, data):
        first_step_id = list(self.steps.keys())[0]
        processed_data = self.process_step(data, first_step_id)
        return processed_data

    def process_step(self, data, step_id):
        step = self.steps.get(step_id)
        if step is None:
            raise ValueError(f"Step with ID {step_id} not found")

        step_type = step["type"]
        if step_type not in self.step_map:
            raise ValueError(f"Unknown step type: {step_type}")

        StepClass = self.step_map[step_type]
        if StepClass is not None:
            params = step.get("params", {})
            processor = StepClass(**params)
            processed_data = processor.process(data)
        else:
            processed_data = data

        for next_step_id in step.get("next", []):
            processed_data = self.process_step(processed_data, next_step_id)

        return processed_data


class DbfsMeasurement:
    def __init__(self, bit_depth=16):
        self.bit_depth = bit_depth

    def process(self, data):
        rms_val = self.rms(data)
        db_val = self.rms_to_db(rms_val)
        return db_val

    @staticmethod
    def rms(data):
        return np.sqrt(np.mean(data**2))

    def rms_to_db(self, rms_val):
        if rms_val == 0:
            return -np.inf
        reference = 2 ** (self.bit_depth - 1)
        return 20 * np.log10(rms_val / reference)

class BandpassFilter:
    def __init__(self, low_cut, high_cut, buffer_size, filter_coeffs, segment_size):
        self.low_cut = low_cut
        self.high_cut = high_cut
        self.buffer_size = buffer_size
        self.buffer = []
        self.filter_coeffs = filter_coeffs
        self.segment_size = segment_size

    def process(self, data):
        self.buffer.append(data)
        if len(self.buffer) > self.buffer_size:
            self.buffer.pop(0)

        if len(self.buffer) < self.buffer_size:
            return None

        processed_data = self.overlap_save_algorithm(self.buffer)
        return processed_data

    def overlap_save_algorithm(self, chunks):
        signal = np.concatenate(chunks)
        return overlap_save(signal, self.filter_coeffs, self.segment_size)

def overlap_save(signal, filter_coeffs, segment_size):
    filter_length = len(filter_coeffs)
    overlap = filter_length - 1

    padded_signal = np.pad(signal, (overlap, 0))

    output = np.zeros(len(signal))

    for start in range(0, len(padded_signal) - overlap, segment_size):
        end = start + segment_size
        chunk = padded_signal[start:end]
        filtered_chunk = fftconvolve(chunk, filter_coeffs, mode="full")[:segment_size]
        output[start:start + len(filtered_chunk)] += filtered_chunk

    return output[:len(signal)]

class Downsample:
    def __init__(self, factor):
        self.factor = factor

    def process(self, data):
        return data[::self.factor]

