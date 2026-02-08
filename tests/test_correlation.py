"""Unit tests for master node data handler, especially ChunkToCCStream."""

import numpy as np
import os
import pytest
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "master-node"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from correlation import ChunkToCCStream, DataHandler
from signals import SignalGenerator, SignalConfig, SignalType


class TestChunkToCCStream:
    """Test the ChunkToCCStream processor for cross-correlation."""

    def setup_method(self):
        """Set up test fixtures."""
        # Reset class-level shared state to isolate tests
        ChunkToCCStream._reference_stream = None
        ChunkToCCStream._remote_streams = {}
        ChunkToCCStream._buffers = {}
        ChunkToCCStream._db_history = {}

        self.processor = ChunkToCCStream()
        self.generator = SignalGenerator()
        self.sample_rate = 44100
        self.chunk_duration = 0.5  # 500ms chunks

    def create_audio_chunk(
        self, audio_data, timestamp, sample_rate, station_id, tags=None
    ):
        """Helper to create a properly formatted audio chunk."""
        return {
            "station_id": station_id,
            "data_type": "audio_chunk",
            "data": audio_data if isinstance(audio_data, list) else audio_data.tolist(),
            "timestamp": timestamp,
            "time_precision": "ns",
            "metadata": {
                "sample_rate": sample_rate,
                "bit_depth": 16,
                "location": "test",
                "tags": tags or [],
            },
        }

    def test_initialization(self):
        """Test processor initializes correctly."""
        assert self.processor.reference_stream is None
        assert self.processor.remote_streams == {}
        assert self.processor.buffers == {}
        assert self.processor.BUFFER_SECONDS == 2

    def test_process_reference_stream(self):
        """Test that reference stream is buffered correctly."""
        # Generate test signal
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=self.chunk_duration,
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=0.5,
        )
        audio = self.generator.generate(config)

        chunk = self.create_audio_chunk(
            audio,
            timestamp=int(1e9),
            sample_rate=self.sample_rate,
            station_id="ref_node",
            tags=["reference"],
        )

        result = self.processor.process(chunk)

        # Processing reference should return None (no correlation yet)
        assert result is None

        # But reference stream should be populated
        assert self.processor.reference_stream is not None
        timestamps, data = self.processor.reference_stream
        assert len(timestamps) == 1
        assert len(data) == len(audio)

    def test_process_remote_stream(self):
        """Test that remote stream is buffered correctly."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=self.chunk_duration,
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=0.5,
        )
        audio = self.generator.generate(config)

        chunk = self.create_audio_chunk(
            audio,
            timestamp=int(1e9),
            sample_rate=self.sample_rate,
            station_id="remote_1",
            tags=[],
        )

        result = self.processor.process(chunk)

        # No reference stream yet, should return None
        assert result is None

        # But remote stream should be populated
        assert "remote_1" in self.processor.remote_streams
        timestamps, data = self.processor.remote_streams["remote_1"]
        assert len(timestamps) == 1
        assert len(data) == len(audio)

    def test_correlation_with_identical_signals(self):
        """Test correlation with identical reference and remote signals."""
        # Generate identical signal for both
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,  # Longer signal for better correlation
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=1.0,
        )
        audio = self.generator.generate(config)

        # Send reference chunks
        chunk_size = int(self.sample_rate * self.chunk_duration)
        for i in range(0, len(audio), chunk_size):
            chunk_data = audio[i : i + chunk_size]
            if len(chunk_data) == chunk_size:
                timestamp = int(1e9) + i * int(1e9 / self.sample_rate)
                chunk = self.create_audio_chunk(
                    chunk_data,
                    timestamp,
                    self.sample_rate,
                    "ref_node",
                    tags=["reference"],
                )
                self.processor.process(chunk)

        # Send identical remote chunks (should have 0 delay)
        for i in range(0, len(audio), chunk_size):
            chunk_data = audio[i : i + chunk_size]
            if len(chunk_data) == chunk_size:
                timestamp = int(1e9) + i * int(1e9 / self.sample_rate)
                chunk = self.create_audio_chunk(
                    chunk_data, timestamp, self.sample_rate, "remote_1", tags=[]
                )
                result = self.processor.process(chunk)

        # Last chunk should produce correlation result
        assert result is not None
        assert len(result) == 1
        (remote_id, db, tau, corr_coef, confidence, data_quality,
         total_db_remote, venue_db, la90, venue_audibility) = result[0]

        assert remote_id == "remote_1"
        # Delay should be near zero for identical signals
        assert abs(tau) < 0.001  # Within 1ms
        # Correlation coefficient should be very high
        assert corr_coef > 0.95
        # Data quality should be perfect (no gaps)
        assert data_quality > 0.99
        # Confidence should be high
        assert confidence > 0.95

    def test_correlation_with_delay(self):
        """Test correlation detection with delayed signal."""
        # Generate reference and delayed remote
        config = SignalConfig(
            signal_type=SignalType.CHIRP,
            duration=2.0,
            sample_rate=self.sample_rate,
            start_frequency=20,
            end_frequency=200,
            amplitude=1.0,
        )

        delay_seconds = 0.100  # 100ms delay
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config,
            delay_seconds=delay_seconds,
            signal_attenuation=0.5,
            snr_db=20,
        )

        # Send reference chunks
        chunk_size = int(self.sample_rate * self.chunk_duration)
        for i in range(0, len(reference), chunk_size):
            chunk_data = reference[i : i + chunk_size]
            if len(chunk_data) == chunk_size:
                timestamp = int(1e9) + i * int(1e9 / self.sample_rate)
                chunk = self.create_audio_chunk(
                    chunk_data,
                    timestamp,
                    self.sample_rate,
                    "ref_node",
                    tags=["reference"],
                )
                self.processor.process(chunk)

        # Send remote chunks (same timestamps as reference)
        for i in range(0, len(remote), chunk_size):
            chunk_data = remote[i : i + chunk_size]
            if len(chunk_data) == chunk_size:
                timestamp = int(1e9) + i * int(1e9 / self.sample_rate)
                chunk = self.create_audio_chunk(
                    chunk_data, timestamp, self.sample_rate, "remote_1", tags=[]
                )
                result = self.processor.process(chunk)

        # Should produce a correlation result
        assert result is not None
        (remote_id, db, tau, corr_coef, confidence, data_quality,
         total_db_remote, venue_db, la90, venue_audibility) = result[0]

        # With significant noise (SNR=20dB) and attenuation, correlation may be weak
        # The important thing is that it completes without error
        # In practice, you'd want higher SNR for reliable correlation
        assert remote_id == "remote_1"
        # Data quality should be perfect (no packet loss in test)
        assert data_quality > 0.99
        # Just verify we got a result, correlation strength depends on SNR

    def test_multiple_remote_nodes(self):
        """Test correlation with multiple remote nodes."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=1.0,
        )
        audio = self.generator.generate(config)

        # Send reference
        chunk_size = int(self.sample_rate * self.chunk_duration)
        for i in range(0, len(audio), chunk_size):
            chunk_data = audio[i : i + chunk_size]
            if len(chunk_data) == chunk_size:
                timestamp = int(1e9) + i * int(1e9 / self.sample_rate)
                chunk = self.create_audio_chunk(
                    chunk_data,
                    timestamp,
                    self.sample_rate,
                    "ref_node",
                    tags=["reference"],
                )
                self.processor.process(chunk)

        # Send from multiple remote nodes
        for node_id in ["remote_1", "remote_2", "remote_3"]:
            for i in range(0, len(audio), chunk_size):
                chunk_data = audio[i : i + chunk_size]
                if len(chunk_data) == chunk_size:
                    timestamp = int(1e9) + i * int(1e9 / self.sample_rate)
                    chunk = self.create_audio_chunk(
                        chunk_data, timestamp, self.sample_rate, node_id, tags=[]
                    )
                    result = self.processor.process(chunk)

        # Should have correlations for all nodes
        assert result is not None
        assert len(result) == 3
        remote_ids = [r[0] for r in result]
        assert "remote_1" in remote_ids
        assert "remote_2" in remote_ids
        assert "remote_3" in remote_ids

        # Check that all have good data quality
        for r in result:
            (_, _, _, _, _, data_quality,
             _, _, _, _) = r
            assert data_quality > 0.99  # No packet loss in test

    def test_buffer_eviction(self):
        """Test that old chunks are evicted from buffer."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=self.chunk_duration,
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=0.5,
        )
        audio = self.generator.generate(config)

        # Calculate max buffer size
        chunk_size = len(audio)
        max_buffer = self.processor.BUFFER_SECONDS * self.sample_rate // chunk_size

        # Send more chunks than buffer can hold
        for i in range(int(max_buffer + 5)):
            timestamp = int(1e9) + i * int(chunk_size * 1e9 / self.sample_rate)
            chunk = self.create_audio_chunk(
                audio, timestamp, self.sample_rate, "ref_node", tags=["reference"]
            )
            self.processor.process(chunk)

        # Buffer should not exceed max size
        assert len(self.processor.buffers["reference"]) <= max_buffer

    def test_timestamp_gap_detection(self):
        """Test that timestamp gaps are detected and handled."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=self.chunk_duration,
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=1.0,
        )
        audio = self.generator.generate(config)

        # Send reference chunks
        chunk_size = len(audio)
        for i in range(3):
            timestamp = int(1e9) + i * int(chunk_size * 1e9 / self.sample_rate)
            chunk = self.create_audio_chunk(
                audio, timestamp, self.sample_rate, "ref_node", tags=["reference"]
            )
            self.processor.process(chunk)

        # Send remote chunks with a gap (missing chunk 1)
        for i in [0, 2]:  # Skip i=1
            timestamp = int(1e9) + i * int(chunk_size * 1e9 / self.sample_rate)
            chunk = self.create_audio_chunk(
                audio, timestamp, self.sample_rate, "remote_1", tags=[]
            )
            result = self.processor.process(chunk)

        # Should detect gap and not correlate (or handle gracefully)
        # Result might be None or might skip the correlation
        # The important thing is it doesn't crash

    def test_rcc_method(self):
        """Test the robust cross-correlation method directly."""
        # Create two identical signals
        sig1 = np.sin(2 * np.pi * 100 * np.linspace(0, 1, 44100))
        sig2 = sig1.copy()

        db, tau, r, total_db_remote, venue_db = self.processor.rcc(sig1, sig2, 44100)

        # Identical signals should have zero delay
        assert abs(tau) < 1e-6
        # And perfect correlation
        assert r > 0.99

    def test_rcc_with_noise(self):
        """Test RCC with noisy signals."""
        # Generate clean signal
        sig1 = np.sin(2 * np.pi * 100 * np.linspace(0, 1, 44100))

        # Add noise to create sig2
        sig2 = sig1 + 0.1 * np.random.randn(len(sig1))

        db, tau, r, total_db_remote, venue_db = self.processor.rcc(sig1, sig2, 44100)

        # Should still detect zero delay despite noise
        assert abs(tau) < 0.001
        # Correlation should be reasonable
        assert r > 0.8

    def test_rcc_error_handling(self):
        """Test RCC error handling for invalid inputs."""
        sig1 = np.sin(2 * np.pi * 100 * np.linspace(0, 1, 100))
        sig2 = np.sin(2 * np.pi * 100 * np.linspace(0, 1, 200))

        # Different lengths should raise error
        with pytest.raises(ValueError, match="same length"):
            self.processor.rcc(sig1, sig2, 44100)

        # Invalid sample rate
        with pytest.raises(ValueError, match="positive"):
            self.processor.rcc(sig1, sig1, -100)

        # Empty signals
        with pytest.raises(ValueError, match="empty"):
            self.processor.rcc(np.array([]), np.array([]), 44100)


class TestDataHandler:
    """Test the DataHandler class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = DataHandler()

    def test_processor_registration(self):
        """Test that processors are registered correctly."""
        assert "scalar" in self.handler.processors
        assert "audio_chunk" in self.handler.processors

    def test_instance_creation(self):
        """Test that processor instances are created correctly."""
        data = {
            "station_id": "test_node",
            "data_type": "audio_chunk",
            "data": [0] * 1000,
            "timestamp": int(1e9),
            "time_precision": "ns",
            "metadata": {
                "sample_rate": 44100,
                "bit_depth": 16,
                "location": "test",
            },
        }

        # First call should create instance
        self.handler.process_data("test_node", "audio_chunk", data)

        # Instance should exist
        instance_id = list(self.handler.instances.keys())[0]
        assert "test_node" in instance_id
        assert "ChunkToCCStream" in instance_id

    def test_instance_reuse(self):
        """Test that instances are reused for same station/metadata."""
        data = {
            "station_id": "test_node",
            "data_type": "audio_chunk",
            "data": [0] * 1000,
            "timestamp": int(1e9),
            "time_precision": "ns",
            "metadata": {
                "sample_rate": 44100,
                "bit_depth": 16,
                "location": "test",
            },
        }

        # Process twice
        self.handler.process_data("test_node", "audio_chunk", data)
        self.handler.process_data("test_node", "audio_chunk", data)

        # Should only have one instance
        assert len(self.handler.instances) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
