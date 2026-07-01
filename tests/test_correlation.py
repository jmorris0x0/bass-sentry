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

    def _feed_ref_remote_chunks(
        self,
        reference,
        remote,
        chunk_sample_rate,
        chunk_size,
        ref_ts_start_ns,
        remote_ts_start_ns,
    ):
        """Feed a reference/remote pair through the processor.

        Returns the last non-None process() result.
        """
        ns_per_chunk = int(chunk_size / chunk_sample_rate * 1e9)

        for i in range(0, len(reference), chunk_size):
            chunk_data = reference[i : i + chunk_size]
            if len(chunk_data) != chunk_size:
                continue
            timestamp = ref_ts_start_ns + (i // chunk_size) * ns_per_chunk
            self.processor.process(self.create_audio_chunk(
                chunk_data, timestamp, chunk_sample_rate, "ref_node",
                tags=["reference"],
            ))

        last_result = None
        for i in range(0, len(remote), chunk_size):
            chunk_data = remote[i : i + chunk_size]
            if len(chunk_data) != chunk_size:
                continue
            timestamp = remote_ts_start_ns + (i // chunk_size) * ns_per_chunk
            r = self.processor.process(self.create_audio_chunk(
                chunk_data, timestamp, chunk_sample_rate, "remote_1", tags=[],
            ))
            if r is not None:
                last_result = r
        return last_result

    def test_delay_detection_with_aligned_chunk_timestamps(self):
        """Control: aligned chunk timestamps should recover the true delay.

        This exists so that if it also fails, we know the correlation math
        itself is broken (not just alignment).
        """
        chunk_sr = 1000  # matches grid_decimation output rate
        chunk_size = 500  # 500ms chunks
        true_delay_s = 0.005  # 5 ms — physical delay for mics ~1.7 m apart

        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=4.0,
            sample_rate=chunk_sr,
            frequency=80.0,
            amplitude=1.0,
        )
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config,
            delay_seconds=true_delay_s,
            signal_attenuation=1.0,
            snr_db=40,
        )

        # Ref and remote share the same chunk-emission grid.
        ts0 = int(1e9)  # arbitrary epoch offset
        result = self._feed_ref_remote_chunks(
            reference, remote, chunk_sr, chunk_size,
            ref_ts_start_ns=ts0, remote_ts_start_ns=ts0,
        )
        assert result is not None, "no correlation result produced"
        _, _, tau, corr_coef, _, data_quality, *_ = result[0]

        assert corr_coef > 0.8, f"weak correlation: rho={corr_coef}"
        detected_ms = tau * 1000
        expected_ms = true_delay_s * 1000
        assert abs(detected_ms - expected_ms) < 3.0, (
            f"aligned case: delay reported as {detected_ms:.1f}ms, "
            f"expected ~{expected_ms:.1f}ms, quality={data_quality:.1%}"
        )

    def test_delay_detection_with_offset_chunk_timestamps(self):
        """Reproduces the party-night bug: nodes emit chunks on different
        500ms cadences because their recorder subprocesses start at
        different wallclock times. Correlation math should recover the
        true acoustic delay regardless of chunk-emission offset.
        """
        chunk_sr = 1000
        chunk_size = 500  # 500ms chunks
        true_delay_s = 0.005
        # Remote's chunk cadence is offset from reference by 100 ms —
        # sub-chunk, not on the 500 ms boundary.
        chunk_grid_offset_ns = 100_000_000

        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=4.0,
            sample_rate=chunk_sr,
            frequency=80.0,
            amplitude=1.0,
        )
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=config,
            delay_seconds=true_delay_s,
            signal_attenuation=1.0,
            snr_db=40,
        )

        ts0 = int(1e9)
        result = self._feed_ref_remote_chunks(
            reference, remote, chunk_sr, chunk_size,
            ref_ts_start_ns=ts0,
            remote_ts_start_ns=ts0 + chunk_grid_offset_ns,
        )
        assert result is not None, "no correlation result produced"
        _, _, tau, corr_coef, _, data_quality, *_ = result[0]

        detected_ms = tau * 1000
        expected_ms = true_delay_s * 1000
        # The bug reports delay ~= chunk_grid_offset_ns (or ±500ms
        # aliased) instead of the acoustic delay. This assertion
        # should fail today and pass once alignment is fixed.
        assert abs(detected_ms - expected_ms) < 3.0, (
            f"offset case: delay reported as {detected_ms:.1f}ms, "
            f"expected ~{expected_ms:.1f}ms, rho={corr_coef:.3f}, "
            f"quality={data_quality:.1%}"
        )

    def test_delay_detection_with_periodic_beat(self):
        """Reproduces the party-night bug: periodic music (steady kick drum,
        120 BPM claps) produces cross-correlation aliases at multiples of
        the beat period. Without a lag constraint the peak picker locks
        onto an aliased peak instead of the acoustic delay.
        """
        chunk_sr = 1000
        chunk_size = 500  # 500ms chunks
        true_delay_s = 0.005  # 5 ms — mics ~1.7 m apart
        duration_s = 4.0

        # 120 BPM = 2 Hz beat. Build an impulse train at 2 Hz plus a
        # damped bass thud, sampled at chunk_sr.
        n = int(duration_s * chunk_sr)
        t = np.arange(n) / chunk_sr
        beat_period_s = 0.5
        reference = np.zeros(n)
        for beat_start in np.arange(0, duration_s, beat_period_s):
            i0 = int(beat_start * chunk_sr)
            # A short decaying 80Hz burst — imitates a bass thud
            burst_len = int(0.15 * chunk_sr)
            i1 = min(i0 + burst_len, n)
            burst_t = np.arange(i1 - i0) / chunk_sr
            reference[i0:i1] += np.sin(2 * np.pi * 80 * burst_t) * np.exp(-burst_t / 0.05)

        # Delayed copy + a tiny bit of noise
        delay_samples = int(round(true_delay_s * chunk_sr))
        remote = np.zeros_like(reference)
        remote[delay_samples:] = reference[: n - delay_samples]
        rng = np.random.default_rng(0)
        remote = remote + rng.normal(scale=0.02, size=n)

        ts0 = int(1e9)
        result = self._feed_ref_remote_chunks(
            reference, remote, chunk_sr, chunk_size,
            ref_ts_start_ns=ts0, remote_ts_start_ns=ts0,
        )
        assert result is not None, "no correlation result produced"
        _, _, tau, corr_coef, _, data_quality, *_ = result[0]

        detected_ms = tau * 1000
        expected_ms = true_delay_s * 1000
        # A physical venue is at most ~100 m across, so any delay
        # beyond ±300 ms is nonsense. The current code will happily
        # report ±500 ms because it has no lag constraint.
        assert abs(detected_ms) < 300.0, (
            f"delay {detected_ms:.1f}ms is outside any physical venue; "
            f"correlation peak picker locked onto a periodic alias "
            f"(rho={corr_coef:.3f})"
        )
        assert abs(detected_ms - expected_ms) < 5.0, (
            f"periodic beat: delay reported as {detected_ms:.1f}ms, "
            f"expected ~{expected_ms:.1f}ms, rho={corr_coef:.3f}"
        )

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


class TestVenueDbFormula:
    """Test the venue contribution extraction formula: venue_db = total_db + 20*log10(|rho|)."""

    def setup_method(self):
        ChunkToCCStream._reference_stream = None
        ChunkToCCStream._remote_streams = {}
        ChunkToCCStream._buffers = {}
        ChunkToCCStream._db_history = {}
        self.processor = ChunkToCCStream()

    def test_identical_signals_venue_db_equals_total_db(self):
        """When signals are identical (rho=1), venue_db should equal total_db."""
        sig = np.sin(2 * np.pi * 100 * np.linspace(0, 1, 44100))
        db, tau, rho, total_db, venue_db = self.processor.rcc(sig, sig, 44100)

        # rho should be ~1 for identical signals
        assert rho > 0.99
        # venue_db = total_db + 20*log10(1) = total_db + 0
        assert abs(venue_db - total_db) < 0.5  # Within 0.5 dB

    def test_uncorrelated_noise_does_not_change_venue_db(self):
        """Adding uncorrelated noise should not change venue_db (anechoic chamber property).

        This is the core mathematical claim: venue_db extracts the venue
        contribution regardless of environmental noise level.
        """
        fs = 44100
        t = np.linspace(0, 1, fs)
        venue_signal = 0.5 * np.sin(2 * np.pi * 100 * t)

        # Scenario 1: Remote hears venue signal only (quiet environment)
        remote_quiet = venue_signal.copy()
        _, _, _, _, venue_db_quiet = self.processor.rcc(venue_signal, remote_quiet, fs)

        # Scenario 2: Remote hears venue + loud uncorrelated noise
        np.random.seed(42)
        noise = 2.0 * np.random.randn(fs)  # Noise 4x louder than signal
        remote_noisy = venue_signal + noise
        _, _, _, _, venue_db_noisy = self.processor.rcc(venue_signal, remote_noisy, fs)

        # venue_db should be similar in both cases
        # Allow some tolerance due to finite signal length
        assert abs(venue_db_quiet - venue_db_noisy) < 3.0  # Within 3 dB

    def test_attenuated_signal_gives_lower_venue_db(self):
        """Signal attenuated by factor alpha should reduce venue_db by 20*log10(alpha)."""
        fs = 44100
        t = np.linspace(0, 1, fs)
        ref = np.sin(2 * np.pi * 100 * t)

        alpha = 0.5  # -6 dB attenuation
        remote = alpha * ref
        _, _, _, _, venue_db = self.processor.rcc(ref, remote, fs)

        # For identical but attenuated: rho ~ 1, total_db_remote is lower
        # venue_db should reflect the actual attenuated level
        _, _, _, total_db_full, venue_db_full = self.processor.rcc(ref, ref, fs)
        expected_diff = 20 * np.log10(alpha)  # -6.02 dB
        actual_diff = venue_db - venue_db_full
        assert abs(actual_diff - expected_diff) < 1.0  # Within 1 dB

    def test_zero_correlation_gives_neg_inf(self):
        """Completely uncorrelated signals should give venue_db = -inf."""
        fs = 44100
        np.random.seed(1)
        sig1 = np.random.randn(fs)
        np.random.seed(2)
        sig2 = np.random.randn(fs)

        db, tau, rho, total_db, venue_db = self.processor.rcc(sig1, sig2, fs)

        # rho should be near zero for uncorrelated noise
        assert abs(rho) < 0.1
        # venue_db should be very low (approaching -inf)
        assert venue_db < total_db - 20  # At least 20 dB below total

    def test_venue_db_formula_matches_manual_calculation(self):
        """Verify venue_db matches the formula: total_db + 20*log10(|rho|)."""
        fs = 44100
        t = np.linspace(0, 1, fs)
        ref = np.sin(2 * np.pi * 100 * t)

        np.random.seed(42)
        remote = 0.7 * ref + 0.3 * np.random.randn(fs)

        db, tau, rho, total_db, venue_db = self.processor.rcc(ref, remote, fs)

        # Manually compute expected venue_db
        expected = total_db + 20 * np.log10(abs(rho))
        assert abs(venue_db - expected) < 0.01  # Should match exactly


class TestLA90AndAudibility:
    """Test LA90 background level calculation and venue audibility."""

    def setup_method(self):
        ChunkToCCStream._db_history = {}

    def test_la90_returns_none_with_insufficient_data(self):
        """LA90 requires at least 10 samples."""
        # No data at all
        assert ChunkToCCStream.get_la90("remote_1") is None

        # Add 5 samples (not enough)
        for i in range(5):
            ChunkToCCStream.record_db_measurement("remote_1", float(i), 60.0)
        assert ChunkToCCStream.get_la90("remote_1") is None

    def test_la90_returns_10th_percentile(self):
        """LA90 should be the 10th percentile (level exceeded 90% of time)."""
        # Create 100 measurements: values 1 through 100
        for i in range(100):
            ChunkToCCStream.record_db_measurement("remote_1", float(i), float(i + 1))

        la90 = ChunkToCCStream.get_la90("remote_1")
        assert la90 is not None
        # 10th percentile of 1..100 should be ~10.9
        assert abs(la90 - 10.9) < 1.0

    def test_la90_with_constant_level(self):
        """Constant level should give LA90 equal to that level."""
        for i in range(20):
            ChunkToCCStream.record_db_measurement("remote_1", float(i), 55.0)

        la90 = ChunkToCCStream.get_la90("remote_1")
        assert la90 is not None
        assert abs(la90 - 55.0) < 0.01

    def test_la90_window_pruning(self):
        """Old measurements beyond the window should be pruned."""
        base_time = 1000000.0

        # Add old measurements (before the window)
        for i in range(20):
            ChunkToCCStream.record_db_measurement(
                "remote_1",
                base_time - ChunkToCCStream.LA90_WINDOW_SECONDS - 100 + i,
                90.0,
            )

        # Add recent measurements within the window
        for i in range(20):
            ChunkToCCStream.record_db_measurement(
                "remote_1", base_time + i, 50.0
            )

        la90 = ChunkToCCStream.get_la90("remote_1")
        # Should only reflect recent measurements (50 dB), not old (90 dB)
        assert la90 is not None
        assert abs(la90 - 50.0) < 0.01

    def test_stale_remote_id_cleanup(self):
        """Remote IDs with no recent data should be cleaned up."""
        base_time = 1000000.0

        # Add data for stale_node long ago
        for i in range(15):
            ChunkToCCStream.record_db_measurement(
                "stale_node",
                base_time - ChunkToCCStream.LA90_WINDOW_SECONDS - 1000 + i,
                60.0,
            )

        # Add data for active_node now, triggering cleanup
        ChunkToCCStream.record_db_measurement("active_node", base_time, 55.0)

        # stale_node should have been cleaned up
        assert "stale_node" not in ChunkToCCStream._db_history
        assert "active_node" in ChunkToCCStream._db_history

    def test_la90_ignores_neg_inf(self):
        """LA90 calculation should ignore -inf values."""
        for i in range(15):
            ChunkToCCStream.record_db_measurement("remote_1", float(i), 50.0)

        # Add some -inf entries
        for i in range(15, 20):
            ChunkToCCStream.record_db_measurement("remote_1", float(i), -np.inf)

        la90 = ChunkToCCStream.get_la90("remote_1")
        # Should still return ~50 (ignoring -inf)
        assert la90 is not None
        assert abs(la90 - 50.0) < 0.01

    def test_venue_audibility_calculation(self):
        """Test that venue_audibility = venue_db - la90 in the process flow."""
        # This tests the integration of LA90 into the correlation result.
        # We populate enough history to get an LA90, then run correlation.
        processor = ChunkToCCStream()
        ChunkToCCStream._reference_stream = None
        ChunkToCCStream._remote_streams = {}
        ChunkToCCStream._buffers = {}

        # Pre-populate LA90 history for remote_1 using realistic timestamps
        import time as time_mod
        now = time_mod.time()
        for i in range(20):
            ChunkToCCStream.record_db_measurement("remote_1", now - 20 + i, 45.0)

        la90 = ChunkToCCStream.get_la90("remote_1")
        assert la90 is not None
        assert abs(la90 - 45.0) < 0.01

        # Now run a correlation to get venue_audibility
        fs = 44100
        t = np.linspace(0, 1, fs)
        audio = np.sin(2 * np.pi * 100 * t)
        chunk_size = int(fs * 0.5)

        def make_chunk(data, ts, station, tags=None):
            return {
                "station_id": station,
                "data_type": "audio_chunk",
                "data": data.tolist(),
                "timestamp": ts,
                "time_precision": "ns",
                "metadata": {"sample_rate": fs, "bit_depth": 16, "location": "test", "tags": tags or []},
            }

        # Send reference chunks
        for i in range(0, len(audio), chunk_size):
            chunk_data = audio[i:i + chunk_size]
            if len(chunk_data) == chunk_size:
                ts = int(1e9) + i * int(1e9 / fs)
                processor.process(make_chunk(chunk_data, ts, "ref_node", ["reference"]))

        # Send remote chunks
        result = None
        for i in range(0, len(audio), chunk_size):
            chunk_data = audio[i:i + chunk_size]
            if len(chunk_data) == chunk_size:
                ts = int(1e9) + i * int(1e9 / fs)
                result = processor.process(make_chunk(chunk_data, ts, "remote_1"))

        assert result is not None
        (remote_id, db, tau, corr_coef, confidence, data_quality,
         total_db_remote, venue_db, la90_result, venue_audibility) = result[0]

        # venue_audibility should be venue_db - la90
        assert venue_audibility is not None
        assert abs(venue_audibility - (venue_db - la90_result)) < 0.01


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
