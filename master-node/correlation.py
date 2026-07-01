import bisect
import hashlib
import json
import logging
import os
import time
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
from influxdb_client import Point, WritePrecision
import jsonschema
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from scipy.stats import pearsonr

logger = logging.getLogger(__name__)

# Directory for correlation waveform images
CORRELATION_IMAGE_DIR = os.environ.get(
    "CORRELATION_IMAGE_DIR", "/tmp/bass-sentry/correlation_images"
)

PRECISION_MAP = {
    "ns": WritePrecision.NS,
    "us": WritePrecision.US,
    "ms": WritePrecision.MS,
    "s": WritePrecision.S,
}


def save_correlation_plot(
    remote_id: str,
    cc: np.ndarray,
    lags: np.ndarray,
    sample_rate: float,
    detected_lag: int,
    tau: float,
    db: float,
    correlation_coef: float,
) -> Optional[str]:
    """
    Generate and save a cross-correlation waveform plot as PNG.

    Args:
        remote_id: Identifier for the remote station
        cc: Cross-correlation values array
        lags: Lag values array (in samples)
        sample_rate: Audio sample rate in Hz
        detected_lag: Index of peak in correlation
        tau: Time delay in seconds
        db: Correlation amplitude in dB
        correlation_coef: Pearson correlation coefficient

    Returns:
        Path to saved PNG file, or None if save failed
    """
    try:
        # Lazy import matplotlib to avoid startup cost when not needed
        import matplotlib

        matplotlib.use("Agg")  # Non-interactive backend for server use
        import matplotlib.pyplot as plt

        # Create output directory if needed
        os.makedirs(CORRELATION_IMAGE_DIR, exist_ok=True)

        # Convert lags to milliseconds for readability
        lags_ms = lags / sample_rate * 1000
        detected_lag_ms = tau * 1000

        # Normalize correlation for visualization
        cc_normalized = cc / np.max(np.abs(cc)) if np.max(np.abs(cc)) > 0 else cc

        # Create figure with dark theme for better visibility
        fig, ax = plt.subplots(figsize=(12, 5), facecolor="#1a1a2e")
        ax.set_facecolor("#16213e")

        # Plot correlation waveform
        ax.plot(lags_ms, cc_normalized, color="#00d9ff", linewidth=0.8, alpha=0.9)

        # Fill under the curve for visual effect
        ax.fill_between(
            lags_ms, cc_normalized, alpha=0.3, color="#00d9ff", linewidth=0
        )

        # Mark the detected peak
        ax.axvline(
            x=detected_lag_ms,
            color="#ff6b6b",
            linestyle="--",
            linewidth=2,
            label=f"Peak: {detected_lag_ms:.1f}ms",
        )

        # Add zero line
        ax.axhline(y=0, color="#4a4a6a", linestyle="-", linewidth=0.5)

        # Calculate distance (speed of sound ~343 m/s)
        distance_m = abs(tau) * 343

        # Styling
        ax.set_xlabel("Time Lag (ms)", color="#ffffff", fontsize=12)
        ax.set_ylabel("Correlation (normalized)", color="#ffffff", fontsize=12)
        ax.set_title(
            f"Cross-Correlation: {remote_id}\n"
            f"Delay: {detected_lag_ms:.1f}ms | Distance: {distance_m:.1f}m | "
            f"dB: {db:.1f} | r: {correlation_coef:.3f}",
            color="#ffffff",
            fontsize=14,
            pad=15,
        )

        # Axis styling
        ax.tick_params(colors="#cccccc")
        for spine in ax.spines.values():
            spine.set_color("#4a4a6a")

        ax.legend(loc="upper right", facecolor="#16213e", edgecolor="#4a4a6a", labelcolor="#ffffff")

        # Grid
        ax.grid(True, alpha=0.2, color="#4a4a6a")

        # Tight layout
        plt.tight_layout()

        # Save to file
        # Use sanitized remote_id for filename
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in remote_id)
        filename = f"{safe_id}.png"
        filepath = os.path.join(CORRELATION_IMAGE_DIR, filename)

        plt.savefig(filepath, dpi=100, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        logger.debug(f"Saved correlation plot to {filepath}")
        return filepath

    except ImportError:
        logger.warning("matplotlib not installed, skipping correlation plot")
        return None
    except Exception as e:
        logger.error(f"Failed to save correlation plot for {remote_id}: {e}")
        return None


def get_latest_correlation_data() -> Dict[str, Any]:
    """
    Get metadata about the latest correlation images.

    Returns:
        Dict mapping remote_id to image metadata (path, timestamp, etc.)
    """
    result = {}
    if not os.path.exists(CORRELATION_IMAGE_DIR):
        return result

    for filename in os.listdir(CORRELATION_IMAGE_DIR):
        if filename.endswith(".png"):
            filepath = os.path.join(CORRELATION_IMAGE_DIR, filename)
            remote_id = filename[:-4]  # Remove .png extension
            stat = os.stat(filepath)
            result[remote_id] = {
                "path": filepath,
                "filename": filename,
                "modified": stat.st_mtime,
                "size": stat.st_size,
            }

    return result


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
                logger.warning(
                    f"Unknown time precision '{time_precision}', defaulting to seconds"
                )
                write_precision = PRECISION_MAP["s"]
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
            # processed_data is a list of tuples with venue contribution data
            for result in processed_data:
                # Handle different tuple lengths for backwards compatibility
                la90 = None
                venue_audibility = None

                if len(result) == 4:
                    remote_id, db, tau, correlation_coef = result
                    confidence = correlation_coef
                    data_quality = 1.0
                    total_db_remote = db
                    venue_db = db
                elif len(result) == 6:
                    remote_id, db, tau, correlation_coef, confidence, data_quality = result
                    total_db_remote = db
                    venue_db = db
                elif len(result) == 8:
                    (remote_id, db, tau, correlation_coef, confidence, data_quality,
                     total_db_remote, venue_db) = result
                else:
                    # Full format with LA90 and venue_audibility
                    (remote_id, db, tau, correlation_coef, confidence, data_quality,
                     total_db_remote, venue_db, la90, venue_audibility) = result

                point = Point("cross_correlation")
                point.tag("remote_id", remote_id)
                point.field("db", db)  # Legacy field
                point.field("delay_seconds", tau)
                point.field("delay_ms", tau * 1000)
                point.field("correlation_coef", correlation_coef)
                point.field("confidence", confidence)
                point.field("data_quality", data_quality)
                # New fields for venue contribution
                point.field("total_db", total_db_remote)
                point.field("venue_db", venue_db)
                # LA90 and venue audibility (may be None if insufficient data)
                if la90 is not None:
                    point.field("la90", la90)
                    point.field("venue_audibility", venue_audibility)

                # Use the timestamp from the original data
                timestamp = data.get("timestamp", 0)
                time_precision = data.get("time_precision", "s")
                write_precision = PRECISION_MAP.get(time_precision)
                if write_precision is None:
                    logger.warning(
                        f"Unknown time precision '{time_precision}' for {remote_id}, "
                        f"defaulting to seconds"
                    )
                    write_precision = PRECISION_MAP["s"]
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
    LA90_WINDOW_SECONDS = 600  # 10 minute window for LA90 calculation
    # Physical upper bound on peak-search lag. 1 s covers ~343 m of
    # sound propagation. Wider = admits more periodic aliases; tighter =
    # can't measure large venues. Configurable per deployment.
    MAX_LAG_SECONDS = 1.0

    # Class-level shared state so all instances share the same reference stream
    _reference_stream = None
    _remote_streams = {}
    _buffers = {}
    # Track total_db values over time for LA90 calculation per remote
    _db_history = {}  # {remote_id: [(timestamp, total_db), ...]}

    def __init__(self):
        # Use class-level attributes for shared state
        pass

    @property
    def reference_stream(self):
        return ChunkToCCStream._reference_stream

    @reference_stream.setter
    def reference_stream(self, value):
        ChunkToCCStream._reference_stream = value

    @property
    def remote_streams(self):
        return ChunkToCCStream._remote_streams

    @property
    def buffers(self):
        return ChunkToCCStream._buffers

    @classmethod
    def get_la90(cls, remote_id: str) -> float:
        """
        Calculate LA90 for a remote station.

        LA90 is the level exceeded 90% of the time, representing the
        background/quiet level. This is the 10th percentile of measurements.

        Returns:
            LA90 value in dB, or None if insufficient data
        """
        if remote_id not in cls._db_history:
            return None

        history = cls._db_history[remote_id]
        if len(history) < 10:  # Need at least 10 samples
            return None

        # Extract just the dB values
        db_values = [db for _, db in history if db > -np.inf]
        if len(db_values) < 10:
            return None

        # LA90 = 10th percentile (level exceeded 90% of time)
        return float(np.percentile(db_values, 10))

    @classmethod
    def record_db_measurement(cls, remote_id: str, timestamp: float, total_db: float):
        """Record a total_db measurement for LA90 calculation."""
        if remote_id not in cls._db_history:
            cls._db_history[remote_id] = []

        cls._db_history[remote_id].append((timestamp, total_db))

        # Prune old entries beyond the window
        cutoff = timestamp - cls.LA90_WINDOW_SECONDS
        cls._db_history[remote_id] = [
            (t, db) for t, db in cls._db_history[remote_id] if t > cutoff
        ]

        # Remove stale remote_ids whose latest entry is older than the window
        stale_ids = [
            rid for rid, history in cls._db_history.items()
            if not history or history[-1][0] < cutoff
        ]
        for rid in stale_ids:
            del cls._db_history[rid]

    def process(self, data: Dict[str, Any]):
        station_id = data.get("station_id")
        if not station_id:
            logger.warning("Missing station_id in audio chunk data")
            return None

        metadata = data.get("metadata", {})
        sample_rate = metadata.get("sample_rate")
        if sample_rate is None or sample_rate <= 0:
            logger.warning(f"Invalid sample rate for {station_id}: {sample_rate}")
            return None

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
                db, tau, correlation_coef, total_db_remote, venue_db = self.rcc(
                    ref_aligned,
                    remote_aligned,
                    sample_rate,
                    remote_id=remote_id,
                )

                # Adjust confidence based on data quality
                confidence = correlation_coef * data_quality

                # Record measurement for LA90 calculation
                import time as time_module
                current_time = time_module.time()
                ChunkToCCStream.record_db_measurement(remote_id, current_time, total_db_remote)

                # Get LA90 (background level) and compute venue audibility
                la90 = ChunkToCCStream.get_la90(remote_id)
                if la90 is not None:
                    venue_audibility = venue_db - la90
                else:
                    venue_audibility = None

                la90_str = f"LA90={la90:.1f}dB" if la90 is not None else "LA90=N/A"
                logger.info(
                    f"Correlation for {remote_id}: "
                    f"venue={venue_db:.1f}dB, total={total_db_remote:.1f}dB, {la90_str}, "
                    f"delay={tau*1000:.1f}ms, rho={correlation_coef:.3f}, "
                    f"quality={data_quality:.1%}"
                )
                results.append(
                    (remote_id, db, tau, correlation_coef, confidence, data_quality,
                     total_db_remote, venue_db, la90, venue_audibility)
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

        # Use binary insertion to maintain sorted order - O(n) vs O(n log n) for sort
        item = (timestamp, audio_data)
        # bisect.insort uses the first element of tuple for comparison by default
        bisect.insort(buffer, item)

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

        # Use binary insertion to maintain sorted order - O(n) vs O(n log n) for sort
        item = (timestamp, audio_data)
        bisect.insort(buffer, item)

        if len(buffer) > max_buffer_size:
            buffer.pop(0)  # Evict oldest data chunk

        if buffer:
            timestamps, audio_data_chunks = zip(*buffer)
            self.remote_streams[remote_id] = (
                np.array(timestamps),
                np.concatenate(audio_data_chunks),
            )

    def rcc(self, sig1, sig2, fs, ref_amp=10000.0, remote_id=None, save_plot=True):
        """
        Robust cross-correlation using FFT for efficiency.

        Args:
            sig1: Reference signal (numpy array)
            sig2: Remote signal (numpy array)
            fs: Sample rate in Hz
            ref_amp: Reference amplitude for dB calculation
            remote_id: Optional identifier for the remote station (for plot saving)
            save_plot: Whether to save a correlation plot image (default True)

        Returns:
            tuple: (db, tau, correlation_coef, total_db_remote, venue_db)
                - db: Cross-correlation amplitude in dB (legacy)
                - tau: Time delay in seconds (positive = sig2 delayed)
                - correlation_coef: Normalized correlation coefficient (rho)
                - total_db_remote: Total dB measured at remote location
                - venue_db: Venue contribution in dB (the key metric!)

        The venue_db is computed using:
            venue_db = total_db_remote + 20 * log10(|correlation_coef|)

        This formula mathematically extracts the venue's contribution,
        removing environmental noise. See docs/math.md for derivation.
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

        # Constrain peak search to physically plausible lags. Sound
        # propagation between stations is bounded by MAX_LAG_SECONDS *
        # speed_of_sound; anything outside this range cannot be a real
        # acoustic delay. Excludes periodic-signal aliases that would
        # otherwise let the argmax lock onto a peak at ±(N × beat_period)
        # instead of the true delay.
        max_lag_samples = int(ChunkToCCStream.MAX_LAG_SECONDS * fs)
        center = n - 1  # index of lag = 0 in the length-(2n-1) axis
        lo = max(0, center - max_lag_samples)
        hi = min(len(cc), center + max_lag_samples + 1)

        # Peak within the physical search window
        window_offset = int(np.argmax(np.abs(cc[lo:hi])))
        peak_idx = lo + window_offset
        shift = lags[peak_idx]
        tau = shift / fs

        # Calculate amplitude and convert to dB
        amplitude = np.abs(cc[peak_idx])

        # Avoid log(0) errors
        if amplitude < 1e-10:
            db = -np.inf
            logger.warning("Correlation amplitude near zero, setting dB to -inf")
        else:
            db = 20 * np.log10(amplitude / ref_amp)

        # Calculate normalized correlation coefficient (rho)
        # This is the key value for venue contribution extraction
        # rho = R_xr(tau) / (x_rms * r_rms)
        sig1_std = np.std(sig1_centered)
        sig2_std = np.std(sig2_centered)
        if sig1_std > 0 and sig2_std > 0:
            # Normalized correlation coefficient at the peak lag
            rho = cc[peak_idx] / (n * sig1_std * sig2_std)
        else:
            rho = 0.0

        # Also compute Pearson correlation for reference (at zero lag)
        try:
            pearson_r, _ = pearsonr(sig1, sig2)
        except Exception as e:
            logger.warning(f"Failed to calculate Pearson correlation: {e}")
            pearson_r = 0.0

        # Compute total dB at remote location
        # Using RMS amplitude, referenced to a standard level
        sig2_rms = np.sqrt(np.mean(sig2**2))
        if sig2_rms > 1e-10:
            # Reference to 1.0 for normalized signals, adjust for actual levels
            total_db_remote = 20 * np.log10(sig2_rms / ref_amp)
        else:
            total_db_remote = -np.inf

        # THE KEY FORMULA: venue_db = total_db + 20*log10(|rho|)
        # This extracts venue contribution, removing environmental noise
        if abs(rho) > 1e-10:
            venue_db = total_db_remote + 20 * np.log10(abs(rho))
        else:
            venue_db = -np.inf
            logger.warning(f"Correlation coefficient near zero for {remote_id}, venue_db set to -inf")

        # Save correlation plot if requested and remote_id is provided
        if save_plot and remote_id:
            save_correlation_plot(
                remote_id=remote_id,
                cc=cc,
                lags=lags,
                sample_rate=fs,
                detected_lag=peak_idx,
                tau=tau,
                db=db,
                correlation_coef=rho,
            )

        return db, tau, rho, total_db_remote, venue_db


