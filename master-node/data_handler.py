import logging
import jsonschema
from typing import Dict, Any
from influxdb_client import Point, WritePrecision

logger = logging.getLogger(__name__)


class DataHandler:
    def __init__(self):
        self.processors = {
            "db_fs": dbFS(),
            "scalar_ts": ScalarTS(),
            "chunk_to_scalar": ChunkToScalar(),
            "chunk_to_stream": ChunkToStream(),
        }

    def process_data(self, data_type, data):
        if data_type in self.processors:
            return self.processors[data_type].process(data)
        else:
            logger.warning(f"Unknown data type: {data_type}")
            return None


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


class dbFS(DataProcessor):
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["station_id", "chunk", "fs"],
        "properties": {
            "station_id": {"type": "string"},
            "data_type": {"type": "string"},
            "timestamp": {"type": "integer"},
            "time_precision": {
                "type": "string",
                "enum": ["ns", "us", "ms", "s", "m", "h"],
            },
            "chunk": {
                "type": "array",
                "items": {"type": "number"},
            },
            "bands": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "fs": {"type": "number"},
            "tags": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
    }

    def validate(self, data: Dict[str, Any]) -> bool:
        try:
            jsonschema.validate(instance=data, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            logger.error(f"Data validation failed: {e}")
            return False
        return True

    def process(self, json_data: Dict[str, Any]) -> Point:
        if not self.validate(json_data):
            return None

        chunk = np.array(json_data["chunk"])
        fs = json_data["fs"]
        bands = json_data.get("bands", {"NoFilter": [0, fs / 2]})

        point = Point("dBFS")
        point.tag("station_id", json_data["station_id"])

        timestamp = json_data.get("timestamp")
        if timestamp is not None:
            time_precision = json_data.get("time_precision", WritePrecision.NS)
            point.time(timestamp, time_precision)

        tags = json_data.get("tags", {})
        for key, value in tags.items():
            point.tag(key, value)

        for band_name, (lowcut, highcut) in bands.items():
            filtered_chunk = bandpass_filter_fft(chunk, lowcut, highcut, fs)
            rms_value = np.sqrt(np.mean(filtered_chunk**2))
            dbfs_value = 20 * np.log10(rms_value / np.max(np.abs(chunk)))
            point.field(f"{band_name}_dbFS", dbfs_value)

        return point


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
