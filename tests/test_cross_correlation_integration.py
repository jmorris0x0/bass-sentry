# tests/test_cross_correlation_integration.py
"""Integration tests for cross-correlation using signal generator.

This shows how to test the actual ChunkToCCStream processor with known signals.
"""

import numpy as np
import pytest
from unittest.mock import Mock

from common.signals import SignalGenerator, SignalConfig, SignalType


class TestCrossCorrelationIntegration:
    """Test cross-correlation with realistic scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = SignalGenerator()
        self.sample_rate = 44100
        self.chunk_duration = 0.5  # 500ms chunks like real system

    def create_test_chunks(
        self, signal, chunk_duration, sample_rate, timestamp_start=0
    ):
        """Split a signal into chunks matching the system format."""
        samples_per_chunk = int(chunk_duration * sample_rate)
        chunks = []

        for i in range(0, len(signal), samples_per_chunk):
            chunk_data = signal[i : i + samples_per_chunk]
            if len(chunk_data) == samples_per_chunk:  # Skip partial chunks
                timestamp = timestamp_start + int(i / sample_rate * 1e9)  # nanoseconds
                chunk = {
                    "data_type": "audio_chunk",
                    "data": chunk_data.tolist(),
                    "timestamp": timestamp,
                    "time_precision": "ns",
                    "metadata": {
                        "sample_rate": sample_rate,
                        "bit_depth": 16,
                        "location": "test",
                        "tags": [],
                    },
                }
                chunks.append(chunk)

        return chunks

    def test_simple_delay_detection(self):
        """Test detecting a simple delay between reference and remote."""
        # Generate test signals
        config = SignalConfig(
            signal_type=SignalType.CHIRP,
            duration=5.0,
            sample_rate=self.sample_rate,
            start_frequency=20,
            end_frequency=200,
            amplitude=1.0,
        )

        delay = 0.150  # 150ms
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config,
            delay_seconds=delay,
            signal_attenuation=0.5,
            snr_db=20,  # Good SNR for initial testing
        )

        # Create chunks
        ref_chunks = self.create_test_chunks(
            reference, self.chunk_duration, self.sample_rate
        )
        remote_chunks = self.create_test_chunks(
            remote, self.chunk_duration, self.sample_rate
        )

        # Tag reference chunks
        for chunk in ref_chunks:
            chunk["metadata"]["tags"].append("reference")

        # Simulate processing these chunks
        print(
            f"Created {len(ref_chunks)} reference chunks and {len(remote_chunks)} remote chunks"
        )
        print(f"Expected delay: {delay * 1000:.1f}ms")

        # This is where you would feed chunks to ChunkToCCStream
        # For now, we'll do a simple correlation on the full signals
        self._verify_correlation(reference, remote, delay)

    def test_low_snr_detection(self):
        """Test detection with signal buried in noise."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=3.0,
            sample_rate=self.sample_rate,
            frequency=50.0,  # Bass frequency
            amplitude=1.0,
        )

        delay = 0.08  # 80ms
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config,
            delay_seconds=delay,
            signal_attenuation=0.1,
            snr_db=-6,  # Signal weaker than noise
        )

        ref_chunks = self.create_test_chunks(
            reference, self.chunk_duration, self.sample_rate
        )
        remote_chunks = self.create_test_chunks(
            remote, self.chunk_duration, self.sample_rate
        )

        # Tag reference
        for chunk in ref_chunks:
            chunk["metadata"]["tags"].append("reference")

        print(f"Low SNR test: {len(ref_chunks)} chunks each")
        self._verify_correlation(reference, remote, delay, tolerance_ms=5.0)

    def test_streaming_correlation(self):
        """Test correlation with streaming chunks (not all at once)."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=10.0,  # Longer signal
            sample_rate=self.sample_rate,
            frequency=63.0,
            amplitude=1.0,
        )

        delay = 0.200  # 200ms
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config, delay_seconds=delay, signal_attenuation=0.3, snr_db=15
        )

        ref_chunks = self.create_test_chunks(
            reference, self.chunk_duration, self.sample_rate
        )
        remote_chunks = self.create_test_chunks(
            remote, self.chunk_duration, self.sample_rate
        )

        # Simulate streaming by processing chunks in small batches
        batch_size = 4  # Process 4 chunks at a time (2 seconds)

        for i in range(0, min(len(ref_chunks), len(remote_chunks)), batch_size):
            ref_batch = ref_chunks[i : i + batch_size]
            remote_batch = remote_chunks[i : i + batch_size]

            print(
                f"Processing batch {i//batch_size + 1}: chunks {i} to {i+batch_size-1}"
            )

            # Here you would feed these to ChunkToCCStream
            # and check if correlation is detected after enough data

    def test_multiple_remote_nodes(self):
        """Test correlation with multiple remote nodes."""
        config = SignalConfig(
            signal_type=SignalType.CHIRP,
            duration=4.0,
            sample_rate=self.sample_rate,
            start_frequency=30,
            end_frequency=150,
            amplitude=1.0,
        )

        # Generate reference
        reference = self.generator.generate(config)

        # Create multiple remote signals with different delays
        delays = [0.050, 0.100, 0.200]  # Different distances
        remote_signals = []

        for delay in delays:
            _, remote = self.generator.generate_reference_and_remote(
                source_config=config,
                delay_seconds=delay,
                signal_attenuation=0.4,
                snr_db=10,
            )
            remote_signals.append((delay, remote))

        # Create chunks for all signals
        ref_chunks = self.create_test_chunks(
            reference, self.chunk_duration, self.sample_rate
        )
        for chunk in ref_chunks:
            chunk["metadata"]["tags"].append("reference")

        for i, (delay, remote) in enumerate(remote_signals):
            remote_chunks = self.create_test_chunks(
                remote, self.chunk_duration, self.sample_rate
            )
            # Simulate different station IDs
            for chunk in remote_chunks:
                chunk["station_id"] = f"node_{i+1}"

            print(f"Node {i+1}: expected delay = {delay*1000:.1f}ms")

    def test_time_alignment_issues(self):
        """Test handling of time alignment issues between nodes."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=3.0,
            sample_rate=self.sample_rate,
            frequency=80.0,
            amplitude=1.0,
        )

        delay = 0.100
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config, delay_seconds=delay, signal_attenuation=0.5, snr_db=15
        )

        # Create chunks with misaligned timestamps
        ref_chunks = self.create_test_chunks(
            reference,
            self.chunk_duration,
            self.sample_rate,
            timestamp_start=int(1e9),  # Start at 1 second
        )

        # Remote starts 50ms later (simulating clock drift)
        remote_chunks = self.create_test_chunks(
            remote,
            self.chunk_duration,
            self.sample_rate,
            timestamp_start=int(1.05e9),  # Start at 1.05 seconds
        )

        print("Testing with 50ms timestamp misalignment between nodes")
        # This tests whether the correlation can handle time drift

    def _verify_correlation(self, reference, remote, expected_delay, tolerance_ms=1.0):
        """Helper to verify correlation results."""
        # Normalize
        ref_norm = reference.astype(float) / np.std(reference)
        remote_norm = remote.astype(float) / np.std(remote)

        # Correlate
        correlation = np.correlate(ref_norm, remote_norm, mode="full")
        lags = np.arange(-len(remote) + 1, len(reference))

        # Find peak
        peak_idx = np.argmax(np.abs(correlation))
        detected_lag = lags[peak_idx]
        detected_delay_ms = detected_lag / self.sample_rate * 1000
        expected_delay_ms = expected_delay * 1000

        print(f"  Detected delay: {detected_delay_ms:.1f}ms")
        print(f"  Expected delay: {expected_delay_ms:.1f}ms")
        print(f"  Error: {abs(detected_delay_ms - expected_delay_ms):.1f}ms")
        print(f"  Correlation peak: {correlation[peak_idx]:.3f}")

        assert abs(detected_delay_ms - expected_delay_ms) <= tolerance_ms


class MockChunkToCCStream:
    """Mock implementation to test the interface."""

    def __init__(self):
        self.reference_buffer = []
        self.remote_buffers = {}

    def process(self, data):
        """Process a chunk of data."""
        station_id = data.get("station_id", "unknown")
        tags = data.get("metadata", {}).get("tags", [])

        if "reference" in tags:
            self.reference_buffer.append(data)
        else:
            if station_id not in self.remote_buffers:
                self.remote_buffers[station_id] = []
            self.remote_buffers[station_id].append(data)

        # Would return correlation results when enough data accumulated
        return None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
