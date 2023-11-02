import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from scipy.signal import resample
from collections import deque

logger = logging.getLogger(__name__)


class DAGProcessor:
    def __init__(self, steps, step_map):
        self.steps = steps
        self.step_map = step_map

    def process(self, data, step_id="start"):
        step = self.steps.get(step_id)
        if step is None:
            raise ValueError(f"Step with ID {step_id} not found")

        step_type = step["type"]
        if step_type not in self.step_map:
            raise ValueError(f"Unknown step type: {step_type}")

        StepClass = self.step_map[step_type]
        params = step.get("params", {})
        processor = StepClass(**params) if step_type != "start" else None
        processed_data = processor.process(deepcopy(data)) if processor else data

        next_steps = step.get("next", [])
        if not next_steps:
            return processed_data

        with ThreadPoolExecutor() as executor:
            futures = {}
            for next_step_id in next_steps:
                next_data = deepcopy(processed_data) if len(next_steps) > 1 else processed_data
                future = executor.submit(self.process, next_data, next_step_id)
                futures[future] = next_step_id

            results = []
            for future in as_completed(futures):
                step_id = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.extend(result if isinstance(result, list) else [result])
                except Exception as exc:
                    logger.error(f"Step {step_id} generated an exception: {exc}")

            return results


class SignalProcessor:
    def __init__(self, config):
        self.steps = config.get("steps", {})
        self.step_map = {
            "start": None,  # No processing for the start step
            "dbfs_measurement": DbfsMeasurement,
            "bandpass_filter": BandpassFilter,
            "resample": Resample,
            "metadata_tagger": MetadataTagger,
        }
        self.dag_processor = DAGProcessor(self.steps, self.step_map)

    def process(self, data):
        processed_data = self.dag_processor.process(data)
        return processed_data if isinstance(processed_data, list) else [processed_data]


class DbfsMeasurement:
    def process(self, data):
        bit_depth = data["metadata"]["bit_depth"]
        rms_val = self.rms(data["data"])
        db_val = self.rms_to_db(rms_val, bit_depth)
        processed_data = {
            "data_type": "scalar",
            "timestamp": data["timestamp"],
            "time_precision": data["time_precision"],
            "data": db_val,
            "metadata": {
                "units": "dBFS",
            },
        }
        # Include existing metadata in the processed data
        processed_data["metadata"].update(data["metadata"])
        return processed_data

    @staticmethod
    def rms(data):
        return np.sqrt(np.mean(np.array(data)**2))

    def rms_to_db(self, rms_val, bit_depth):
        if rms_val == 0:
            return -np.inf
        reference = 2 ** (bit_depth - 1)
        return 20 * np.log10(rms_val / reference)


class BandpassFilter:
    def __init__(self, low_cut, high_cut):
        self.low_cut = low_cut
        self.high_cut = high_cut
        self.last_overlap = np.array([])

    def process(self, audio_data):
        sample_rate = audio_data["metadata"]["sample_rate"]  # Get sample rate from the input audio data
        processed_data = self.overlap_save(audio_data["data"], sample_rate)
        audio_data["data_type"] = "audio_chunk"
        audio_data["data"] = processed_data  # Keep it as a NumPy array
        audio_data["metadata"]["filter_low"] = self.low_cut
        audio_data["metadata"]["filter_high"] = self.high_cut
        return audio_data

    def overlap_save(self, signal, sample_rate):
        segment_size = len(signal)
        overlap = segment_size - 1
        output = np.zeros(segment_size)

        if len(self.last_overlap) > 0:
            signal = np.concatenate((self.last_overlap, signal))

        f_signal = np.fft.fft(signal, n=segment_size + overlap)
        frequencies = np.fft.fftfreq(segment_size + overlap, d=1 / sample_rate)
        mask = (frequencies > self.low_cut) & (frequencies < self.high_cut)
        f_signal[~mask] = 0
        filtered_signal = np.fft.ifft(f_signal)
        output[:segment_size] = np.real(filtered_signal[:segment_size])  # Explicitly take the real part

        self.last_overlap = signal[-overlap:]
        return output


class Resample:
    def __init__(self, new_sample_rate):
        self.new_sample_rate = new_sample_rate
        self.buffer = None
        self.old_sample_rate = None

    def process(self, data):
        # Initialize buffer with the size of the first chunk
        if self.buffer is None:
            self.buffer = deque(maxlen=len(data["data"]))

        # Add data to buffer
        self.buffer.extend(data["data"])

        # Set old_sample_rate from the first chunk
        if self.old_sample_rate is None:
            self.old_sample_rate = data["metadata"]["sample_rate"]

       # Log the length of the chunk going in
        #logger.debug(f"Chunk length going in: {len(data['data'])} samples")

        # Add additional debug logging
        #logger.debug(f"Buffer length: {len(self.buffer)}")
        #logger.debug(f"Old sample rate: {self.old_sample_rate}")
        #logger.debug(f"New sample rate: {self.new_sample_rate}")

        # Calculate the number of samples in the resampled data
        num_samples = int(len(self.buffer) * self.new_sample_rate / self.old_sample_rate)

        # Resample the data
        resampled_data = resample(np.array(self.buffer), num_samples)

        #logger.debug(f"Chunk length going out: {len(resampled_data)} samples")

        # Update the data dictionary
        data["data_type"] = "audio_chunk"
        data["data"] = resampled_data
        data["metadata"]["sample_rate"] = self.new_sample_rate

        return data


class MetadataTagger:
    def __init__(self, tag):
        self.tag = tag

    def process(self, data):
        if 'tags' not in data['metadata']:
            data['metadata']['tags'] = []
        data['metadata']['tags'].append(self.tag)
        return data

