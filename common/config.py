"""Configuration management for Bass Sentry using Pydantic for type safety."""

import os
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class AudioConfig(BaseModel):
    """Audio capture and processing configuration."""

    sample_rate: int = Field(44100, description="Audio sample rate in Hz", gt=0)
    bit_depth: int = Field(16, description="Audio bit depth", ge=8, le=32)
    chunk_duration: float = Field(
        0.5, description="Chunk duration in seconds", gt=0, le=10.0
    )
    sending_rate: int = Field(2, description="Chunks per second", gt=0, le=100)
    channels: int = Field(1, description="Number of audio channels", ge=1, le=2)

    @field_validator("bit_depth")
    @classmethod
    def validate_bit_depth(cls, v):
        """Ensure bit depth is supported."""
        if v not in [8, 16, 32]:
            raise ValueError(f"Bit depth must be 8, 16, or 32, got {v}")
        return v

    @property
    def chunk_size(self) -> int:
        """Calculate chunk size in samples."""
        return int(self.sample_rate / self.sending_rate)


class CorrelationConfig(BaseModel):
    """Cross-correlation processing configuration."""

    buffer_seconds: float = Field(
        2.0, description="Correlation buffer length in seconds", gt=0, le=60.0
    )
    reference_dbspl: float = Field(
        120.0, description="Reference SPL level for calibration", ge=0
    )
    max_queue_size: int = Field(
        60, description="Maximum queue size (chunks)", gt=0, le=1000
    )
    min_correlation_threshold: float = Field(
        0.3,
        description="Minimum correlation coefficient to consider valid",
        ge=-1.0,
        le=1.0,
    )
    timestamp_tolerance_percent: float = Field(
        0.1,
        description="Timestamp jitter tolerance as percentage of expected diff",
        ge=0,
        le=1.0,
    )


class MQTTConfig(BaseModel):
    """MQTT broker configuration."""

    host: str = Field("mosquitto", description="MQTT broker hostname")
    port: int = Field(1883, description="MQTT broker port", gt=0, le=65535)
    topic_suffix: str = Field("remote_node", description="Topic suffix for this node")
    keepalive: int = Field(60, description="MQTT keepalive interval in seconds", gt=0)
    qos: int = Field(0, description="MQTT QoS level", ge=0, le=2)


class InfluxDBConfig(BaseModel):
    """InfluxDB configuration."""

    url: str = Field(..., description="InfluxDB URL (e.g., http://influxdb:8086)")
    token: str = Field(..., description="InfluxDB authentication token")
    org: str = Field(..., description="InfluxDB organization name")
    bucket: str = Field(..., description="InfluxDB bucket name")
    timeout: int = Field(
        10000, description="Write timeout in milliseconds", gt=0, le=60000
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        """Ensure URL is properly formatted."""
        if not v.startswith(("http://", "https://")):
            raise ValueError(
                f"InfluxDB URL must start with http:// or https://, got {v}"
            )
        return v.rstrip("/")


class RemoteNodeConfig(BaseSettings):
    """Configuration for remote audio capture nodes."""

    model_config = {"env_prefix": "BASS_SENTRY_"}

    # Node identification
    node_id: Optional[str] = Field(None, description="Unique node identifier")
    location: str = Field("unknown", description="Physical location of node")

    # Audio configuration
    audio: AudioConfig = Field(default_factory=AudioConfig)

    # MQTT configuration
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)

    # Logging
    log_level: str = Field("INFO", description="Logging level")
    log_format: str = Field("json", description="Log format: json or text")

    # NTP
    ntp_server: str = Field("pool.ntp.org", description="NTP server for time sync")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Ensure log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}, got {v}")
        return v_upper


class MasterNodeConfig(BaseSettings):
    """Configuration for master correlation node."""

    model_config = {"env_prefix": "BASS_SENTRY_"}

    # Audio configuration
    audio: AudioConfig = Field(default_factory=AudioConfig)

    # Correlation configuration
    correlation: CorrelationConfig = Field(default_factory=CorrelationConfig)

    # MQTT configuration
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)

    # InfluxDB configuration
    influxdb: InfluxDBConfig

    # Logging
    log_level: str = Field("INFO", description="Logging level")
    log_format: str = Field("json", description="Log format: json or text")

    # Health check
    health_check_interval: int = Field(
        60, description="Health check interval in seconds", gt=0
    )
    unhealthy_threshold: int = Field(
        120, description="Seconds before marking node unhealthy", gt=0
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Ensure log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}, got {v}")
        return v_upper


# Example usage and .env file
EXAMPLE_ENV = """
# Bass Sentry Configuration
# Copy to .env and customize for your deployment

# InfluxDB (required for master node)
BASS_SENTRY_INFLUXDB__URL=http://influxdb:8086
BASS_SENTRY_INFLUXDB__TOKEN=your-secret-token-here
BASS_SENTRY_INFLUXDB__ORG=myorg
BASS_SENTRY_INFLUXDB__BUCKET=mybucket

# MQTT Broker
BASS_SENTRY_MQTT__HOST=mosquitto
BASS_SENTRY_MQTT__PORT=1883

# Audio Settings
BASS_SENTRY_AUDIO__SAMPLE_RATE=44100
BASS_SENTRY_AUDIO__CHUNK_DURATION=0.5
BASS_SENTRY_AUDIO__SENDING_RATE=2

# Correlation Settings
BASS_SENTRY_CORRELATION__BUFFER_SECONDS=2.0
BASS_SENTRY_CORRELATION__REFERENCE_DBSPL=120.0
BASS_SENTRY_CORRELATION__MIN_CORRELATION_THRESHOLD=0.3

# Remote Node Settings
BASS_SENTRY_NODE_ID=pi-1
BASS_SENTRY_LOCATION=dance-floor

# Logging
BASS_SENTRY_LOG_LEVEL=INFO
BASS_SENTRY_LOG_FORMAT=json
"""


def load_remote_config() -> RemoteNodeConfig:
    """Load configuration for remote node from environment."""
    return RemoteNodeConfig()


def load_master_config() -> MasterNodeConfig:
    """Load configuration for master node from environment."""
    return MasterNodeConfig()


if __name__ == "__main__":
    # Example: print configuration schema
    print("Remote Node Configuration Schema:")
    print(RemoteNodeConfig.model_json_schema())
    print("\nMaster Node Configuration Schema:")
    print(MasterNodeConfig.model_json_schema())
    print("\nExample .env file:")
    print(EXAMPLE_ENV)
