import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from scipy.signal import resample

logger = logging.getLogger(__name__)


class SignalProcessor:
    def __init__(self, config):
        self.steps = config.get("steps", {})
        self.step_map = {
            "dbfs_measurement": DbfsMeasurement,
            "bandpass_filter": BandpassFilter,
            "resample": Resample,
        }

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
        params = step.get("params", {})
        processor = StepClass(**params)
        processed_data = processor.process(deepcopy(data))  # Make a deep copy of the data

        if processed_data is None:
            return None  # Do not process further until buffer is full

        next_steps = step.get("next", [])
        if not next_steps:
            return processed_data  # No next steps, return processed data

        # Use ThreadPoolExecutor for parallel processing of branches
        with ThreadPoolExecutor() as executor:
            futures = {}
            for next_step_id in next_steps:
                if len(next_steps) > 1:
                    # Make a deep copy of the processed data if there are multiple next steps
                    next_data = deepcopy(processed_data)
                else:
                    next_data = processed_data  # No need to make a copy if there is only one next step
                future = executor.submit(self.process_step, next_data, next_step_id)
                futures[future] = next_step_id

            results = []
            for future in as_completed(futures):
                step_id = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.extend(result if isinstance(result, list) else [result])  # Flatten the list
                except Exception as exc:
                    logger.error(f"Step {step_id} generated an exception: {exc}")

            return results  # Return list of results


class DbfsMeasurement:
    def process(self, data):
        bit_depth = data["metadata"]["bit_depth"]  # Get bit_depth from data dictionary
        rms_val = self.rms(data["data"])
        db_val = self.rms_to_db(rms_val, bit_depth)
        return {
            "data_type": "scalar",
            "timestamp": data["timestamp"],
            "data": db_val,
            "metadata": {
                "units": "dBFS",
            },
        }

    @staticmethod
    def rms(data):
        return np.sqrt(np.mean(np.array(data)**2))

    def rms_to_db(self, rms_val, bit_depth):
        if rms_val == 0:
            return -np.inf
        reference = 2 ** (bit_depth - 1)
        return 20 * np.log10(rms_val / reference)


class BandpassFilter:
    def __init__(self, low_cut, high_cut, sample_rate):
        self.low_cut = low_cut
        self.high_cut = high_cut
        self.sample_rate = sample_rate
        self.last_overlap = np.array([])

    def process(self, audio_data):
        processed_data = self.overlap_save(audio_data["data"])
        audio_data["data_type"] = "audio_chunk"
        audio_data["data"] = processed_data  # Keep it as a NumPy array
        audio_data["metadata"]["filter_low"] = self.low_cut
        audio_data["metadata"]["filter_high"] = self.high_cut
        return audio_data

    def overlap_save(self, signal):
        segment_size = len(signal)
        overlap = segment_size - 1
        output = np.zeros(segment_size)

        if len(self.last_overlap) > 0:
            signal = np.concatenate((self.last_overlap, signal))

        f_signal = np.fft.fft(signal, n=segment_size + overlap)
        frequencies = np.fft.fftfreq(segment_size + overlap, d=1 / self.sample_rate)
        mask = (frequencies > self.low_cut) & (frequencies < self.high_cut)
        f_signal[~mask] = 0
        filtered_signal = np.fft.ifft(f_signal)
        output[:segment_size] = np.real(filtered_signal[:segment_size])  # Explicitly take the real part

        self.last_overlap = signal[-overlap:]
        return output


class Resample:
    def __init__(self, new_sample_rate):
        self.new_sample_rate = new_sample_rate
        self.buffer = []
        self.old_sample_rate = None  # We'll set this when we process the first chunk

    def process(self, data):
        # Add data to buffer
        data["data"] = np.concatenate([self.buffer, data["data"]])

        if self.old_sample_rate is None:
            # Set old_sample_rate from the first chunk
            self.old_sample_rate = data["metadata"]["sample_rate"]

        # Calculate the number of samples in the resampled data
        num_samples = int(len(data["data"]) * self.new_sample_rate / self.old_sample_rate)


        # Resample the data
        resampled_data = resample(data["data"], num_samples)
    
        # Calculate the number of samples to carry over to the next chunk
        num_carry = num_samples - len(resampled_data)
   

        # Save the last few samples in the buffer for the next chunk
        if num_carry > 0:
            self.buffer = resampled_data[-num_carry:]
            resampled_data = resampled_data[:-num_carry]
        else:
            self.buffer = resampled_data[num_samples:]  # Save the extra samples for the next chunk
            resampled_data = resampled_data[:num_samples]

        # Update the data dictionary
        data["data_type"] = "audio_chunk"
        data["data"] = resampled_data
        data["metadata"]["sample_rate"] = self.new_sample_rate

        return data
