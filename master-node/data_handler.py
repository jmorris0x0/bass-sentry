import json
import logging
import jsonschema
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from typing import Dict, Any, List
import numpy as np
import hashlib
from influxdb_client import Point, WritePrecision
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
            for remote_id, db in processed_data:
                point = Point("cross_correlation")
                point.tag("remote_id", remote_id)
                # ... (add other tags and fields as needed)
                point.field("db", db)
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
        else:
            self.process_remote_stream(data, max_buffer_size)

        if self.reference_stream is not None:
            for remote_id, remote_stream in self.remote_streams.items():
                ref_timestamps, ref_audio_data = self.reference_stream
                remote_timestamps, remote_audio_data = remote_stream
                common_timestamps = np.intersect1d(ref_timestamps, remote_timestamps)

                if len(common_timestamps) > 1:
                    timestamp_diffs = np.diff(common_timestamps)
                    expected_diff = 1 / sample_rate
                    if np.all(np.isclose(timestamp_diffs, expected_diff, atol=1e-6)):
                        ref_audio_data_aligned = ref_audio_data[
                            np.isin(ref_timestamps, common_timestamps)
                        ]
                        remote_audio_data_aligned = remote_audio_data[
                            np.isin(remote_timestamps, common_timestamps)
                        ]

                        if (
                            ref_audio_data_aligned.size > 0
                            and remote_audio_data_aligned.size > 0
                        ):
                            db = self.cross_correlate(
                                ref_audio_data_aligned,
                                remote_audio_data_aligned,
                                sample_rate,
                            )
                            return db

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

    def cross_correlate(self, ref_stream, remote_stream, sample_rate):
        ref_timestamps, ref_audio_data = ref_stream
        remote_timestamps, remote_audio_data = remote_stream

        # Align timestamps.
        # This is necessary because the chunks may not begin at the same time.
        common_timestamps = np.intersect1d(ref_timestamps, remote_timestamps)
        ref_audio_data_aligned = ref_audio_data[
            np.isin(ref_timestamps, common_timestamps)
        ]
        remote_audio_data_aligned = remote_audio_data[
            np.isin(remote_timestamps, common_timestamps)
        ]

        db, tau = self.rcc(
            ref_audio_data_aligned, remote_audio_data_aligned, sample_rate
        )
        return db

    def rcc(self, sig1, sig2, fs, ref_amp=10000.0):
        """
        Robust cross-correlation
        """
        if len(sig1) != len(sig2):
            raise ValueError("Input signals must be the same length")
        if fs <= 0:
            raise ValueError("Sampling frequency must be positive")

        n = len(sig1)
        SIG1 = fft(sig1, n=n)
        SIG2 = fft(sig2, n=n)
        cc = np.real(ifft(SIG2 * np.conj(SIG1)))

        shift = np.argmax(np.abs(cc))
        tau = shift / fs

        amplitude = np.max(np.abs(cc))
        db = 20 * np.log10(amplitude / ref_amp)

        r, _ = pearsonr(sig1, sig2)

        return db, tau


import numpy as np
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


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
