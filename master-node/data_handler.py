import hashlib
import json
import logging
from typing import Dict, Any, List

import numpy as np
from influxdb_client import Point, WritePrecision
import jsonschema
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from scipy.stats import pearsonr
from scipy.fftpack import fft, ifft

logger = logging.getLogger(__name__)

PRECISION_MAP = {
    "ns": WritePrecision.NS,
    "us": WritePrecision.US,
    "ms": WritePrecision.MS,
    "s": WritePrecision.S,
}


class DataHandler:
    def __init__(self):
        self.processors = {
            "scalar": ScalarTS,
            # "chunk_to_scalar": ChunkToScalar,
            # "chunk_to_stream": ChunkToStream,
            "audio_chunk": ChunkToCCStream,
        }
        self.instances = {}

    def process_data(self, station_id: str, data_type: str, data: Dict[str, Any]):
        logger.debug(
            f"Received data: station_id={station_id}, data_type={data_type}, timestamp={data['timestamp']}, metadata={data['metadata']}"
        )

        if data_type not in self.processors:
            logger.warning(f"Unknown data type: {data_type}")
            return None

        processor_class = self.processors[data_type]
        instance_id = self.get_instance_id(
            station_id, data["metadata"], processor_class
        )

        if instance_id not in self.instances:
            logger.info(
                f"Creating new processor instance for station {station_id} with instance ID {instance_id}"
            )
            self.instances[instance_id] = processor_class()

        processor_instance = self.instances[instance_id]
        processed_data = processor_instance.process(data)

        if processed_data is None:
            logger.debug(
                f"Processor instance for station_id={station_id}, instance_id={instance_id} returned None"
            )
            return None

        point = self.create_point(data_type, data, processed_data)
        if point is not None:
            return point
        else:
            return None

    def create_point(
        self, data_type: str, data: Dict[str, Any], processed_data: Any
    ) -> List[Point]:
        points = []
        if data_type == "scalar":
            point = Point(data.get("metadata", {}).get("units", "sensor_data"))
            point.tag("location", data.get("metadata", {}).get("location", ""))

            timestamp = data.get("timestamp", 0)
            time_precision = data.get("time_precision", "s")
            write_precision = PRECISION_MAP.get(time_precision)
            if write_precision is None:
                raise ValueError(f"Unknown time precision: {time_precision}")
            point.time(timestamp, write_precision)

            # Create the 'band' tag
            if "filter_low" in data.get("metadata", {}) and "filter_high" in data.get(
                "metadata", {}
            ):
                band = f"{data['metadata']['filter_low']}-{data['metadata']['filter_high']}Hz"
            else:
                band = "full"
            point.tag("band", band)

            tags = data.get("metadata", {}).get("tags", [])
            for tag in tags:
                point.tag("tag", tag)

            value = processed_data  # This should be a float as per your data schema
            point.field("value", value)
            points.append(point)
        elif data_type == "audio_chunk":
            # processed_data is a list of tuples: (remote_id, db, tau, correlation_coef, confidence, data_quality)
            for result in processed_data:
                # Handle both old format (4 values) and new format (6 values)
                if len(result) == 4:
                    remote_id, db, tau, correlation_coef = result
                    confidence = correlation_coef  # Fallback
                    data_quality = 1.0  # Assume perfect
                else:
                    remote_id, db, tau, correlation_coef, confidence, data_quality = (
                        result
                    )

                point = Point("cross_correlation")
                point.tag("remote_id", remote_id)
                point.field("db", db)
                point.field("delay_seconds", tau)
                point.field("delay_ms", tau * 1000)
                point.field("correlation_coef", correlation_coef)
                point.field("confidence", confidence)
                point.field("data_quality", data_quality)

                # Use the timestamp from the original data
                timestamp = data.get("timestamp", 0)
                time_precision = data.get("time_precision", "s")
                write_precision = PRECISION_MAP.get(time_precision)
                if write_precision is not None:
                    point.time(timestamp, write_precision)

                points.append(point)

        logger.debug(f"Created Point objects: {points}")
        return points

    def get_instance_id(
        self, station_id: str, metadata: Dict[str, Any], processor_class: type
    ) -> str:
        class_name = processor_class.__name__
        metadata_str = json.dumps(metadata, sort_keys=True)
        data_to_hash = f"{station_id}{class_name}{metadata_str}"
        hash_obj = hashlib.md5(data_to_hash.encode())
        instance_id = f"{station_id}-{class_name}-{hash_obj.hexdigest()}"
        logger.debug(
            f"Calculated instance ID: station_id={station_id}, metadata={metadata}, instance_id={instance_id}"
        )
        return instance_id


class DataProcessor:
    def process(self, json_data: Dict[str, Any]) -> Point:
        pass

    def validate(self, data: Dict[str, Any]) -> bool:
        pass


class ScalarTS(DataProcessor):
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["data_type", "timestamp", "time_precision", "data", "metadata"],
        "properties": {
            "data_type": {"type": "string", "enum": ["audio_chunk", "scalar"]},
            "timestamp": {"type": "integer"},
            "time_precision": {
                "type": "string",
                "enum": ["ns", "us", "ms", "s"],
            },
            "data": {"type": "number"},
            "metadata": {
                "type": "object",
                "properties": {
                    "sample_rate": {"type": "integer"},
                    "bit_depth": {"type": "integer"},
                    "filter_low": {"type": "integer"},
                    "filter_high": {"type": "integer"},
                    "units": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["units"],
            },
        },
    }

    def process(self, json_data):
        if not self.validate(json_data):
            return None

        value = json_data["data"]
        return value

    def validate(self, data):
        try:
            validate(instance=data, schema=self.schema)
            return True
        except ValidationError as e:
            logger.warning(f"Data validation error: {e}")
            return False


class ChunkToCCStream(DataProcessor):
    BUFFER_SECONDS = 2
    MAX_GAP_INTERPOLATE = (
        2  # Maximum number of consecutive missing chunks to interpolate
    )
    MIN_DATA_QUALITY = 0.6  # Minimum 60% good data required for correlation

    def __init__(self):
        self.reference_stream = None
        self.remote_streams = {}
        self.buffers = {}

    def process(self, data: Dict[str, Any]):
        station_id = data["station_id"]
        metadata = data.get("metadata", {})
        sample_rate = metadata.get("sample_rate")
        if sample_rate is None or sample_rate <= 0:
            raise ValueError("Invalid sample rate: {}".format(sample_rate))

        chunk_size = len(data["data"])
        max_buffer_size = self.BUFFER_SECONDS * sample_rate // chunk_size

        tags = metadata.get("tags", [])

        if "reference" in tags:
            self.process_reference_stream(data, max_buffer_size)
            # Reference stream update doesn't produce correlation results
            return None
        else:
            self.process_remote_stream(data, max_buffer_size)

        # Compute correlations for all remote streams against reference
        if self.reference_stream is None:
            logger.debug("No reference stream available yet for correlation")
            return None

        results = []
        ref_timestamps, ref_audio_data = self.reference_stream

        for remote_id, remote_stream in self.remote_streams.items():
            remote_timestamps, remote_audio_data = remote_stream

            # Align audio with gap interpolation
            chunk_size = len(data["data"])
            ref_aligned, remote_aligned, data_quality = self._align_audio_with_gaps(
                ref_timestamps,
                ref_audio_data,
                remote_timestamps,
                remote_audio_data,
                chunk_size,
            )

            if ref_aligned is None or remote_aligned is None:
                logger.debug(f"Could not align data for {remote_id}")
                continue

            # Check data quality
            if data_quality < self.MIN_DATA_QUALITY:
                logger.warning(
                    f"Data quality too low for {remote_id}: {data_quality:.1%} "
                    f"(minimum {self.MIN_DATA_QUALITY:.1%})"
                )
                continue

            # Perform cross-correlation
            try:
                db, tau, correlation_coef = self.rcc(
                    ref_aligned,
                    remote_aligned,
                    sample_rate,
                )

                # Adjust confidence based on data quality
                confidence = correlation_coef * data_quality

                logger.info(
                    f"Correlation for {remote_id}: {db:.2f} dB, "
                    f"delay: {tau*1000:.1f}ms, r={correlation_coef:.3f}, "
                    f"quality={data_quality:.1%}, confidence={confidence:.3f}"
                )
                results.append(
                    (remote_id, db, tau, correlation_coef, confidence, data_quality)
                )
            except Exception as e:
                logger.error(f"Correlation failed for {remote_id}: {e}")
                continue

        # Return results or None if no successful correlations
        return results if results else None

    def _align_audio_with_gaps(
        self,
        ref_timestamps,
        ref_audio_data,
        remote_timestamps,
        remote_audio_data,
        chunk_size,
    ):
        """Align audio data, interpolating small gaps where possible.

        Args:
            ref_timestamps: Reference chunk timestamps
            ref_audio_data: Reference audio (concatenated chunks)
            remote_timestamps: Remote chunk timestamps
            remote_audio_data: Remote audio (concatenated chunks)
            chunk_size: Size of one chunk in samples

        Returns:
            Tuple of (ref_aligned, remote_aligned, data_quality) or (None, None, 0)
            data_quality is between 0 and 1, indicating percentage of good data
        """
        # Find all expected timestamps (union of both streams)
        all_timestamps = sorted(set(ref_timestamps) | set(remote_timestamps))

        if len(all_timestamps) == 0:
            return None, None, 0

        ref_aligned_list = []
        remote_aligned_list = []
        quality_flags = []

        for i, ts in enumerate(all_timestamps):
            ref_has = ts in ref_timestamps
            remote_has = ts in remote_timestamps

            if ref_has and remote_has:
                # Both present - perfect!
                ref_chunk = self._get_chunk(
                    ref_audio_data, ref_timestamps, ts, chunk_size
                )
                remote_chunk = self._get_chunk(
                    remote_audio_data, remote_timestamps, ts, chunk_size
                )
                if ref_chunk is not None and remote_chunk is not None:
                    ref_aligned_list.append(ref_chunk)
                    remote_aligned_list.append(remote_chunk)
                    quality_flags.append("good")

            elif not ref_has and remote_has:
                # Reference missing - try to interpolate
                interpolated = self._interpolate_missing_chunk(
                    ref_audio_data, ref_timestamps, ts, chunk_size, all_timestamps, i
                )
                if interpolated is not None:
                    remote_chunk = self._get_chunk(
                        remote_audio_data, remote_timestamps, ts, chunk_size
                    )
                    if remote_chunk is not None:
                        ref_aligned_list.append(interpolated)
                        remote_aligned_list.append(remote_chunk)
                        quality_flags.append("ref_interpolated")
                else:
                    quality_flags.append("ref_missing")

            elif ref_has and not remote_has:
                # Remote missing - try to interpolate
                interpolated = self._interpolate_missing_chunk(
                    remote_audio_data,
                    remote_timestamps,
                    ts,
                    chunk_size,
                    all_timestamps,
                    i,
                )
                if interpolated is not None:
                    ref_chunk = self._get_chunk(
                        ref_audio_data, ref_timestamps, ts, chunk_size
                    )
                    if ref_chunk is not None:
                        ref_aligned_list.append(ref_chunk)
                        remote_aligned_list.append(interpolated)
                        quality_flags.append("remote_interpolated")
                else:
                    quality_flags.append("remote_missing")

        # Calculate data quality
        if len(quality_flags) == 0:
            return None, None, 0

        good = quality_flags.count("good")
        interpolated = quality_flags.count("ref_interpolated") + quality_flags.count(
            "remote_interpolated"
        )
        missing = quality_flags.count("ref_missing") + quality_flags.count(
            "remote_missing"
        )

        # Quality: good chunks = 1.0, interpolated = 0.7, missing = 0.0
        total = len(quality_flags)
        data_quality = (good + interpolated * 0.7) / total if total > 0 else 0

        # Log quality breakdown
        if interpolated > 0 or missing > 0:
            logger.debug(
                f"Alignment quality: good={good}, interpolated={interpolated}, "
                f"missing={missing}, quality={data_quality:.1%}"
            )

        if len(ref_aligned_list) == 0 or len(remote_aligned_list) == 0:
            return None, None, 0

        return (
            np.concatenate(ref_aligned_list),
            np.concatenate(remote_aligned_list),
            data_quality,
        )

    def _get_chunk(self, audio_data, timestamps, target_ts, chunk_size):
        """Extract a chunk from audio data at given timestamp."""
        try:
            idx = np.where(timestamps == target_ts)[0][0]
            start = idx * chunk_size
            end = start + chunk_size

            if end <= len(audio_data):
                return audio_data[start:end]
        except (IndexError, ValueError):
            pass

        return None

    def _interpolate_missing_chunk(
        self, audio_data, timestamps, target_ts, chunk_size, all_timestamps, target_idx
    ):
        """Interpolate a missing chunk using neighbors.

        Returns None if gap is too large or neighbors not available.
        """
        # Find neighbors
        prev_ts = None
        next_ts = None

        # Look backwards for previous chunk
        for i in range(target_idx - 1, -1, -1):
            if all_timestamps[i] in timestamps:
                prev_ts = all_timestamps[i]
                gap_before = target_idx - i
                break

        # Look forward for next chunk
        for i in range(target_idx + 1, len(all_timestamps)):
            if all_timestamps[i] in timestamps:
                next_ts = all_timestamps[i]
                gap_after = i - target_idx
                break

        # Check if gaps are small enough
        if (
            prev_ts is not None
            and (gap_before := target_idx - all_timestamps.index(prev_ts))
            > self.MAX_GAP_INTERPOLATE
        ):
            prev_ts = None

        if (
            next_ts is not None
            and (gap_after := all_timestamps.index(next_ts) - target_idx)
            > self.MAX_GAP_INTERPOLATE
        ):
            next_ts = None

        # Need at least one neighbor
        if prev_ts is None and next_ts is None:
            return None

        # Get neighbor chunks
        prev_chunk = (
            self._get_chunk(audio_data, timestamps, prev_ts, chunk_size)
            if prev_ts
            else None
        )
        next_chunk = (
            self._get_chunk(audio_data, timestamps, next_ts, chunk_size)
            if next_ts
            else None
        )

        # Interpolate based on available neighbors
        if prev_chunk is not None and next_chunk is not None:
            # Linear interpolation between both neighbors
            return (prev_chunk.astype(np.float32) + next_chunk.astype(np.float32)) / 2
        elif prev_chunk is not None:
            # Use previous chunk (hold)
            return prev_chunk.copy()
        elif next_chunk is not None:
            # Use next chunk (pre-fill)
            return next_chunk.copy()

        return None

    def process_reference_stream(self, data: Dict[str, Any], max_buffer_size: int):
        buffer = self.buffers.setdefault("reference", [])
        timestamp = data["timestamp"]
        audio_data = data["data"]
        buffer.append((timestamp, audio_data))

        buffer.sort(key=lambda x: x[0])  # Sort by timestamp

        if len(buffer) > max_buffer_size:
            buffer.pop(0)  # Evict oldest data chunk

        if buffer:
            timestamps, audio_data_chunks = zip(*buffer)
            self.reference_stream = (
                np.array(timestamps),
                np.concatenate(audio_data_chunks),
            )

    def process_remote_stream(self, data: Dict[str, Any], max_buffer_size: int):
        remote_id = data["station_id"]
        buffer = self.buffers.setdefault(remote_id, [])
        timestamp = data["timestamp"]
        audio_data = data["data"]
        buffer.append((timestamp, audio_data))

        buffer.sort(key=lambda x: x[0])  # Sort by timestamp

        if len(buffer) > max_buffer_size:
            buffer.pop(0)  # Evict oldest data chunk

        if buffer:
            timestamps, audio_data_chunks = zip(*buffer)
            self.remote_streams[remote_id] = (
                np.array(timestamps),
                np.concatenate(audio_data_chunks),
            )

    def rcc(self, sig1, sig2, fs, ref_amp=10000.0):
        """
        Robust cross-correlation using FFT for efficiency.

        Args:
            sig1: Reference signal (numpy array)
            sig2: Remote signal (numpy array)
            fs: Sample rate in Hz
            ref_amp: Reference amplitude for dB calculation

        Returns:
            tuple: (db, tau, correlation_coef)
                - db: Cross-correlation amplitude in dB
                - tau: Time delay in seconds (positive = sig2 delayed)
                - correlation_coef: Pearson correlation coefficient
        """
        if len(sig1) != len(sig2):
            raise ValueError(
                f"Input signals must be the same length: {len(sig1)} vs {len(sig2)}"
            )
        if fs <= 0:
            raise ValueError("Sampling frequency must be positive")
        if len(sig1) == 0:
            raise ValueError("Input signals cannot be empty")

        # Convert to numpy arrays and ensure float64 for numerical stability
        sig1 = np.asarray(sig1, dtype=np.float64)
        sig2 = np.asarray(sig2, dtype=np.float64)

        # Normalize signals to prevent numerical issues
        sig1_mean = np.mean(sig1)
        sig2_mean = np.mean(sig2)
        sig1_centered = sig1 - sig1_mean
        sig2_centered = sig2 - sig2_mean

        # FFT-based cross-correlation
        # Use scipy's correlate for correct normalization and lag handling
        from scipy.signal import correlate

        n = len(sig1)

        # Perform cross-correlation
        cc = correlate(sig2_centered, sig1_centered, mode="full", method="fft")

        # Lag array: negative lags mean sig2 leads sig1, positive means sig2 lags
        lags = np.arange(-n + 1, n)

        # Find peak correlation
        peak_idx = np.argmax(np.abs(cc))
        shift = lags[peak_idx]
        tau = shift / fs

        # Calculate amplitude and convert to dB
        amplitude = np.abs(cc[np.argmax(np.abs(cc))])

        # Avoid log(0) errors
        if amplitude < 1e-10:
            db = -np.inf
            logger.warning("Correlation amplitude near zero, setting dB to -inf")
        else:
            db = 20 * np.log10(amplitude / ref_amp)

        # Calculate Pearson correlation coefficient for validation
        try:
            r, _ = pearsonr(sig1, sig2)
        except Exception as e:
            logger.warning(f"Failed to calculate Pearson correlation: {e}")
            r = 0.0

        return db, tau, r


class ChunkToTimeSeries(DataProcessor):
    BUFFER_SECONDS = 2

    def __init__(self):
        super().__init__()
        self.buffers = {}

    def process(self, data: Dict[str, Any]):
        station_id = data["station_id"]
        metadata = data.get("metadata", {})
        sample_rate = metadata.get("sample_rate", 44100)
        if sample_rate <= 0:
            raise ValueError(f"Invalid sample rate: {sample_rate}")

        max_buffer_size = int(self.BUFFER_SECONDS * sample_rate)

        timestamp = data["timestamp"]
        audio_data = np.array(data["data"])

        if audio_data.ndim == 1:
            audio_data = audio_data[:, np.newaxis]

        self.process_stream(
            station_id, timestamp, audio_data, max_buffer_size, sample_rate
        )

    def process_stream(
        self, station_id, timestamp, audio_data, max_buffer_size, sample_rate
    ):
        buffer = self.buffers.setdefault(
            station_id, {"timestamps": [], "data": np.array([])}
        )
        buffer["timestamps"].append(timestamp)
        buffer["data"] = (
            np.concatenate((buffer["data"], audio_data), axis=1)
            if buffer["data"].size
            else audio_data
        )

        if buffer["data"].shape[1] > max_buffer_size:
            excess_length = buffer["data"].shape[1] - max_buffer_size
            buffer["data"] = buffer["data"][:, excess_length:]
            buffer["timestamps"] = buffer["timestamps"][-max_buffer_size:]

        self.detect_gaps_or_overlaps(station_id, buffer["timestamps"], sample_rate)

    def detect_gaps_or_overlaps(self, stream_id, timestamps, sample_rate):
        if not timestamps:
            return  # Skip if buffer is empty

        timestamps_array = np.array(timestamps)
        timestamp_diffs = np.diff(timestamps_array)
        expected_diff = 1 / sample_rate
        anomalies = np.where(np.abs(timestamp_diffs - expected_diff) > 1e-6)[0]

        if anomalies.size > 0:
            for anomaly_index in anomalies:
                if timestamp_diffs[anomaly_index] > expected_diff:
                    logger.error(
                        f"Gap detected in stream {stream_id} between "
                        f"{timestamps_array[anomaly_index]} and "
                        f"{timestamps_array[anomaly_index + 1]}"
                    )
                else:
                    logger.error(
                        f"Overlap detected in stream {stream_id} at "
                        f"{timestamps_array[anomaly_index]}"
                    )


class ChunkToScalar(DataProcessor):
    def process(self, data):
        # process chunked time-series data into a scalar value
        return processed_data


class ChunkToStream(DataProcessor):
    def process(self, data):
        # process chunked time-series data into timestamped streams
        return processed_data


# When you have a new data type to process, you'll do the following:

# Create a new DataProcessor subclass for the new data type.
# Update the processors dictionary in the DataHandler class to include the new processor.
# Ensure that the data includes the correct data_type when it's sent to the handle_data_point method.
# That's it! The handle_data_point method will automatically use the correct processor for the new data type.
