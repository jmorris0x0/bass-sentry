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
            "chunk_to_scalar": ChunkToScalar,
            "chunk_to_stream": ChunkToStream,
            "chunk_to_cc_stream": ChunkToCCStream,
        }
        self.instances = {}






    def process_data(self, station_id: str, data_type: str, data: Dict[str, Any]):
        logger.debug(f"Received data: station_id={station_id}, data_type={data_type}, data={data}")
        
        if data_type not in self.processors:
            logger.warning(f"Unknown data type: {data_type}")
            return None

        processor_class = self.processors[data_type]
        instance_id = self.get_instance_id(station_id, data["metadata"], processor_class)

        if instance_id not in self.instances:
            logger.info(
                f"Creating new processor instance for station {station_id} with instance ID {instance_id}"
            )
            self.instances[instance_id] = processor_class()

        processor_instance = self.instances[instance_id]
        processed_data = processor_instance.process(data)
        
        if processed_data is None:
            logger.debug(f"Processor instance for station_id={station_id}, instance_id={instance_id} returned None")
            return None

        point = self.create_point(data_type, data, processed_data)
        if point is not None:
            return point
        else:
            return None


    def create_point(self, data_type: str, data: Dict[str, Any], processed_data: Any) -> Point:
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
            if "filter_low" in data.get("metadata", {}) and "filter_high" in data.get("metadata", {}):
                band = f"{data['metadata']['filter_low']}-{data['metadata']['filter_high']}"
            else:
                band = "full"
            point.tag("band", band)
            
            tags = data.get("metadata", {}).get("tags", [])
            for tag in tags:
                point.tag("tag", tag)
            
            value = processed_data  # This should be a float as per your data schema
            point.field("value", value)
        else:
            # Handle other data types accordingly
            pass

        logger.debug(f"Created Point object: {point}")
        return point


    def get_instance_id(self, station_id: str, metadata: Dict[str, Any], processor_class: type) -> str:
        class_name = processor_class.__name__
        metadata_str = json.dumps(metadata, sort_keys=True)
        data_to_hash = f"{station_id}{class_name}{metadata_str}"
        hash_obj = hashlib.md5(data_to_hash.encode())
        instance_id = f"{station_id}-{class_name}-{hash_obj.hexdigest()}"
        logger.debug(f"Calculated instance ID: station_id={station_id}, metadata={metadata}, instance_id={instance_id}")
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
