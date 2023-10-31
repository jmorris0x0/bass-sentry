import logging
import jsonschema
from typing import Dict, Any, List
import numpy as np
from influxdb_client import Point, WritePrecision
from scipy.stats import pearsonr
from scipy.fftpack import fft, ifft

logger = logging.getLogger(__name__)


class DataHandler:
    def __init__(self):
        self.processors = {
            "scalar": ScalarTS,
            "chunk_to_scalar": ChunkToScalar,
            "chunk_to_stream": ChunkToStream,
            "chunk_to_cc_stream": ChunkToCCStream,
        }
        self.instances = {}

    def process_data(
        self, station_id: str, data_type: str, data: Dict[str, Any]
    ) -> Point:
        if data_type not in self.processors:
            logger.warning(f"Unknown data type: {data_type}")
            return None

        processor_class = self.processors[data_type]
        instance_key = (station_id, data_type)

        if instance_key not in self.instances:
            logger.info(
                f"Creating new processor instance for station {station_id} and data type {data_type}"
            )
            self.instances[instance_key] = processor_class()

        processor_instance = self.instances[instance_key]
        return processor_instance.process(data)


class DataProcessor:
    def process(self, json_data: Dict[str, Any]) -> Point:
        pass

    def validate(self, data: Dict[str, Any]) -> bool:
        pass


class ScalarTS(DataProcessor):
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["station_id", "data_type", "fields"],
        "properties": {
            "station_id": {"type": "string"},
            "data_type": {"type": "string"},
            "timestamp": {"type": "integer"},
            "time_precision": {
                "type": "string",
                "enum": ["ns", "us", "ms", "s", "m", "h"],
            },
            "tags": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "fields": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
        },
    }

    def validate(self, data):
        try:
            jsonschema.validate(instance=data, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            logger.error(f"Data validation failed: {e}")
            return False
        return True

    def process(self, json_data):
        if not self.validate(json_data):
            return None

        point = Point("dBFS")
        point.tag("station_id", json_data["station_id"])

        timestamp = json_data.get("timestamp")
        if timestamp is not None:
            time_precision = json_data.get("time_precision", WritePrecision.NS)
            point.time(timestamp, time_precision)

        tags = json_data.get("tags", {})
        for key, value in tags.items():
            point.tag(key, value)

        fields = json_data["fields"]
        for key, value in fields.items():
            point.field(key, value)

        return point





class ChunkToCCStream(DataProcessor):
    def __init__(self):
        self.reference_stream = None  # Buffer for reference stream
        self.remote_streams = {}  # Dictionary to store buffers for each remote stream

    def process(self, data: Dict[str, Any]) -> Point:
        station_id = data["station_id"]
        stream_type = data.get("stream_type")
        if stream_type == "reference":
            self.process_reference_stream(data)
        elif stream_type == "remote":
            self.process_remote_stream(data)
        else:
            logger.error("Unknown stream type: {}".format(stream_type))
            return None

        if self.reference_stream is not None:
            for remote_id, remote_stream in self.remote_streams.items():
                db, tau = self.cross_correlate(self.reference_stream, remote_stream)
                point = Point("CrossCorrelation")
                point.tag("station_id", station_id)
                point.tag("remote_id", remote_id)
                point.field("db", db)
                point.field("tau", tau)
                return point

    def process_reference_stream(self, data: Dict[str, Any]):
        # Logic to handle reference stream data
        self.reference_stream = data["chunk"]

    def process_remote_stream(self, data: Dict[str, Any]):
        # Logic to handle remote stream data
        remote_id = data["remote_id"]
        self.remote_streams[remote_id] = data["chunk"]

    def cross_correlate(self, ref_stream, remote_stream):
        fs = 44100  # Assume a fixed sampling rate for now
        db, tau, _, _ = rcc(ref_stream, remote_stream, fs)
        return db, tau

    def rcc(self, sig1, sig2, fs, ref_amp=10000.0):
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

        return db, tau, _, _


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
