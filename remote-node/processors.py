"""
Signal Processing DAG (Directed Acyclic Graph)

This module implements a configurable audio processing pipeline. Audio chunks
flow through a DAG defined in JSON, allowing parallel processing paths.

Example DAG:
    start ─┬─> bandpass_filter ──> resample ──> dbfs_measurement
           │
           └─> dbfs_measurement (raw)

The DAG is defined in a JSON config file and executed by DAGProcessor.
Each step type maps to a processor class (BandpassFilter, DbfsMeasurement, etc.).

See docs/CODE_GUIDE.md for full documentation.
"""

import atexit
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy

import numpy as np
from scipy.signal import resample, butter, sosfilt, sosfilt_zi

# dB offset applied to every dbfs_measurement output. Adjust to make
# reported SPL match a trusted reference (phone SPL meter against
# pink noise). 105 empirically matched the fleet's current gain-knob
# positions against NIOSH SLM at 80 dB SPL, but historical 6am ambient
# comparison to two-year-old screenshots showed all nodes reading
# ~4 dB lower than they should relative to last year's calibration
# (which was the reference for the 105 dB neighbor-complaint threshold
# used in the DJ Booth dashboard). Bumped to 109 so those thresholds
# stay meaningful this year. Purely a label offset; does not change
# the ADC's physical clipping level.
REFERENCE_DBSPL = 109

logger = logging.getLogger(__name__)

# Module-level shared executor for DAG processing
_dag_executor = None
_dag_executor_lock = threading.Lock()


def _get_dag_executor(max_workers=4):
    """Get or create the shared DAG executor."""
    global _dag_executor
    if _dag_executor is None:
        with _dag_executor_lock:
            if _dag_executor is None:
                _dag_executor = ThreadPoolExecutor(max_workers=max_workers)
                # Register cleanup on interpreter shutdown
                atexit.register(_shutdown_dag_executor)
    return _dag_executor


def _shutdown_dag_executor():
    """Shutdown the shared executor."""
    global _dag_executor
    if _dag_executor is not None:
        _dag_executor.shutdown(wait=False)
        _dag_executor = None


class DAGProcessor:
    def __init__(self, steps, step_map, max_workers=4, strict=False):
        """Initialize DAG processor.

        Args:
            steps: DAG step definitions
            step_map: Mapping of step types to processor classes
            max_workers: Maximum concurrent workers
            strict: If True, re-raise exceptions instead of logging and continuing
        """
        self.steps = steps
        self.step_map = step_map
        self.max_workers = max_workers
        self.strict = strict
        self.errors = []  # Track errors for inspection

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

        # Use shared executor instead of creating new one each time
        executor = _get_dag_executor(self.max_workers)
        futures = {}
        for next_step_id in next_steps:
            next_data = (
                deepcopy(processed_data) if len(next_steps) > 1 else processed_data
            )
            future = executor.submit(self.process, next_data, next_step_id)
            futures[future] = next_step_id

        results = []
        for future in as_completed(futures):
            current_step_id = futures[future]
            try:
                result = future.result()
                if result is not None:
                    results.extend(result if isinstance(result, list) else [result])
            except Exception as exc:
                error_info = {
                    "step_id": current_step_id,
                    "exception": exc,
                    "exception_type": type(exc).__name__,
                }
                self.errors.append(error_info)
                logger.error(
                    f"Step {current_step_id} failed: {type(exc).__name__}: {exc}",
                    exc_info=True,  # Include traceback
                )
                if self.strict:
                    raise

        return results


class SignalProcessor:
    def __init__(self, config):
        self.steps = config.get("steps", {})
        self.step_map = {
            "start": None,  # No processing for the start step
            "dbfs_measurement": DbfsMeasurement,
            "bandpass_filter": BandpassFilter,
            "resample": Resample,
            "grid_decimation_resample": GridDecimationResample,
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
                "units": "dBSPL" if REFERENCE_DBSPL != 0 else "dBFS",
            },
        }

        # Include existing metadata in the processed data
        processed_data["metadata"].update(data["metadata"])
        return processed_data

    @staticmethod
    def rms(data):
        return np.sqrt(np.mean(np.array(data) ** 2))

    def rms_to_db(self, rms_val, bit_depth):
        if rms_val == 0:
            return -np.inf
        reference = 2 ** (bit_depth - 1)
        return 20 * np.log10(rms_val / reference) + REFERENCE_DBSPL


class BandpassFilter:
    """
    IIR Butterworth bandpass filter - 10-100x faster than FFT-based filtering.

    Uses scipy's Second-Order Sections (SOS) format for numerical stability.
    Maintains filter state across chunks for continuous processing.
    """

    def __init__(self, low_cut, high_cut, order=4):
        self.low_cut = low_cut
        self.high_cut = high_cut
        self.order = order
        self.sos = None
        self.zi = None
        self.last_sample_rate = None

    def process(self, audio_data):
        sample_rate = audio_data["metadata"]["sample_rate"]

        # Initialize or update filter coefficients if sample rate changed
        if self.sos is None or sample_rate != self.last_sample_rate:
            self._init_filter(sample_rate)
            self.last_sample_rate = sample_rate

        # Convert to numpy array if needed
        signal = np.array(audio_data["data"])

        # Apply filter with state (zi) for continuous processing across chunks
        filtered_signal, self.zi = sosfilt(self.sos, signal, zi=self.zi)

        audio_data["data_type"] = "audio_chunk"
        audio_data["data"] = filtered_signal
        audio_data["metadata"]["filter_low"] = self.low_cut
        audio_data["metadata"]["filter_high"] = self.high_cut
        audio_data["metadata"]["filter_order"] = self.order
        return audio_data

    def _init_filter(self, sample_rate):
        """Initialize Butterworth bandpass filter coefficients."""
        nyquist = sample_rate / 2.0

        # Validate frequencies
        if self.low_cut <= 0:
            raise ValueError(f"low_cut must be > 0, got {self.low_cut}")
        if self.high_cut >= nyquist:
            raise ValueError(
                f"high_cut must be < Nyquist ({nyquist}), got {self.high_cut}"
            )
        if self.low_cut >= self.high_cut:
            raise ValueError(
                f"low_cut ({self.low_cut}) must be < high_cut ({self.high_cut})"
            )

        # Design Butterworth bandpass filter in SOS format (more stable than ba format)
        self.sos = butter(
            self.order,
            [self.low_cut / nyquist, self.high_cut / nyquist],
            btype="band",
            output="sos",
        )

        # Initialize filter state for continuous processing
        # sosfilt_zi returns (n_sections, 2) for 1D signals
        self.zi = sosfilt_zi(self.sos) * 0  # Zero initial state


class GridDecimationResample:
    def __init__(self, new_sample_rate):
        logging.debug(f"Initializing with new_sample_rate: {new_sample_rate}")

        if not self.is_valid_frequency(new_sample_rate):
            raise ValueError(
                "New sample rate must result in an integer number of nanoseconds per sample"
            )
        logging.debug(f"New sample rate is valid.")
        self.new_sample_rate = new_sample_rate

    @staticmethod
    def is_valid_frequency(frequency):
        period_ns = 1 / frequency * 1e9
        return period_ns.is_integer()

    def process(self, packet):
        original_sample_rate = packet["metadata"]["sample_rate"]
        data_start_time_ns = packet["timestamp"]
        original_samples = np.array(packet["data"])
        num_original = len(original_samples)

        # Ensure original_samples is not empty
        if num_original == 0:
            raise ValueError("original_samples is empty")

        logging.debug(f"Original data_start_time_ns: {data_start_time_ns}")

        # Pre-compute period constants (avoid repeated division)
        sample_period_ns = int(1e9 / self.new_sample_rate)
        original_period_ns = 1e9 / original_sample_rate

        # Determine if the data start time is already aligned with the desired sample grid
        if data_start_time_ns % sample_period_ns == 0:
            aligned_start_time_ns = data_start_time_ns
        else:
            # Align to the next sample on the grid
            aligned_start_time_ns = (
                (data_start_time_ns // sample_period_ns) + 1
            ) * sample_period_ns

        # Create the time series for original sample times
        # Using np.arange with pre-computed period is faster than division in array expression
        original_times_ns = (
            np.arange(num_original) * original_period_ns + data_start_time_ns
        )

        # Calculate the number of target samples based on the last original timestamp
        num_target_samples = int(
            np.ceil(
                (original_times_ns[-1] - aligned_start_time_ns)
                * self.new_sample_rate
                / 1e9
            )
        )

        # Generate the target timestamps starting from the aligned wallclock second
        # np.arange with integer step is faster than multiplication
        target_times_ns = (
            np.arange(num_target_samples, dtype=np.float64) * sample_period_ns
            + aligned_start_time_ns
        )

        # Before raising the ValueError, log the relevant information
        if (
            target_times_ns[0] < original_times_ns[0]
            or target_times_ns[-1] > original_times_ns[-1]
        ):
            logging.error(
                f"Alignment issue: Target start time {target_times_ns[0]} or end time {target_times_ns[-1]} is outside the range of original times {original_times_ns[0]} to {original_times_ns[-1]}"
            )
            raise ValueError("Target times fall outside the range of original times")

        # Vectorized approach for finding the closest indices
        # searchsorted finds insertion points (indices where target would go)
        indices = np.searchsorted(original_times_ns, target_times_ns, side="left")

        # Clip to valid range first to avoid out-of-bounds
        indices = np.clip(indices, 1, len(original_samples) - 1)

        # Calculate distances to left neighbor (indices-1) and current position (indices)
        # This is faster than creating diff_right array with minimum operations
        diff_left = target_times_ns - original_times_ns[indices - 1]
        diff_right = original_times_ns[indices] - target_times_ns

        # Choose closest: if diff_right < diff_left, use indices; else use indices-1
        # This creates a boolean mask which we use for efficient selection
        use_right = diff_right < diff_left
        closest_indices = np.where(use_right, indices, indices - 1)

        # Create the resampled array by selecting the closest original samples
        resampled_data = original_samples[closest_indices]

        # Update the packet with the resampled data
        packet["timestamp"] = int(target_times_ns[0])
        packet["data"] = resampled_data.tolist()
        packet["metadata"]["sample_rate"] = self.new_sample_rate

        return packet


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
        # logger.debug(f"Chunk length going in: {len(data['data'])} samples")

        # Add additional debug logging
        # logger.debug(f"Buffer length: {len(self.buffer)}")
        # logger.debug(f"Old sample rate: {self.old_sample_rate}")
        # logger.debug(f"New sample rate: {self.new_sample_rate}")

        # Calculate the number of samples in the resampled data
        num_samples = int(
            len(self.buffer) * self.new_sample_rate / self.old_sample_rate
        )

        # Resample the data
        resampled_data = resample(np.array(self.buffer), num_samples)

        # logger.debug(f"Chunk length going out: {len(resampled_data)} samples")

        # Update the data dictionary
        data["data_type"] = "audio_chunk"
        data["data"] = resampled_data
        data["metadata"]["sample_rate"] = self.new_sample_rate

        # TODO: This doesn't upate the timestamp.This is hard because we don't
        # know the start time of the original data because of buffering. We can
        # probably get around this by using the timestamp of the first chunk,
        # but this will cause problems if the first chunk is empty.
        # We could also give indexes to the chunks and use that to calculate
        # the timestamp. -JM

        return data


class MetadataTagger:
    def __init__(self, tag):
        self.tag = tag

    def process(self, data):
        if "tags" not in data["metadata"]:
            data["metadata"]["tags"] = []
        data["metadata"]["tags"].append(self.tag)
        return data
