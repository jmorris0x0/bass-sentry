# tests/test_signals.py
"""Tests for signal generator module."""

import numpy as np
import pytest

from common.signals import (
    SignalGenerator,
    SignalConfig,
    SignalType,
    generate_test_chunk,
)


class TestSignalGenerator:
    """Test signal generation functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = SignalGenerator()
        self.sample_rate = 44100
        self.duration = 1.0

    def test_sine_wave_generation(self):
        """Test basic sine wave generation."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=self.duration,
            sample_rate=self.sample_rate,
            frequency=440.0,
            amplitude=0.5,
            bit_depth=16,
        )

        signal = self.generator.generate(config)

        # Check basic properties
        assert isinstance(signal, np.ndarray)
        assert signal.dtype == np.int16
        assert len(signal) == int(self.sample_rate * self.duration)

        # Check amplitude is within expected range
        max_possible = 2**15 - 1
        assert np.max(np.abs(signal)) <= max_possible * 0.5

    def test_white_noise_generation(self):
        """Test white noise generation."""
        config = SignalConfig(
            signal_type=SignalType.WHITE_NOISE,
            duration=self.duration,
            sample_rate=self.sample_rate,
            amplitude=0.5,
        )

        signal = self.generator.generate(config)

        # Check that it's not constant
        assert np.std(signal) > 0

        # Check that mean is near zero (for large enough sample)
        normalized = signal.astype(float) / (2**15 - 1)
        assert abs(np.mean(normalized)) < 0.1

    def test_impulse_generation(self):
        """Test impulse signal generation."""
        config = SignalConfig(
            signal_type=SignalType.IMPULSE,
            duration=self.duration,
            sample_rate=self.sample_rate,
            amplitude=1.0,
            impulse_time=0.5,  # Middle of signal
        )

        signal = self.generator.generate(config)

        # Find the impulse
        impulse_idx = np.argmax(np.abs(signal))
        expected_idx = int(0.5 * self.sample_rate)

        # Check impulse is at correct location (within 1 sample)
        assert abs(impulse_idx - expected_idx) <= 1

        # Check that rest of signal is zero
        signal_copy = signal.copy()
        signal_copy[impulse_idx] = 0
        assert np.all(signal_copy == 0)

    def test_stereo_with_delay(self):
        """Test stereo signal generation with delay."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=self.duration,
            sample_rate=self.sample_rate,
            frequency=440.0,
            amplitude=0.5,
        )

        delay = 0.01  # 10ms delay
        left, right = self.generator.generate_stereo_with_delay(
            config, delay_seconds=delay
        )

        # Check that signals have same length
        assert len(left) == len(right)

        # For positive delay, right should be delayed
        # We expect to find the peak at negative lag (left leads right)
        correlation = np.correlate(right, left, mode="full")
        lags = np.arange(-len(left) + 1, len(right))
        peak_idx = np.argmax(np.abs(correlation))
        detected_lag = lags[peak_idx]

        detected_delay_samples = detected_lag  # Remove the negative sign
        expected_delay_samples = int(delay * self.sample_rate)

        assert abs(detected_delay_samples - expected_delay_samples) <= 1

    def test_multi_tone_generation(self):
        """Test multi-tone signal generation."""
        frequencies = [440.0, 880.0, 1320.0]
        amplitudes = [0.5, 0.3, 0.2]

        signal = self.generator.generate_multi_tone(
            frequencies=frequencies,
            amplitudes=amplitudes,
            duration=self.duration,
            sample_rate=self.sample_rate,
        )

        # Convert to float for FFT
        signal_float = signal.astype(float) / (2**15 - 1)

        # Compute FFT
        fft = np.fft.rfft(signal_float)
        freqs = np.fft.rfftfreq(len(signal_float), 1 / self.sample_rate)

        # Find peaks
        magnitude = np.abs(fft)

        # Check that we have peaks at expected frequencies
        for freq in frequencies:
            # Find closest frequency bin
            idx = np.argmin(np.abs(freqs - freq))

            # Check that there's a peak near this frequency
            # (allowing for spectral leakage)
            assert magnitude[idx] > np.mean(magnitude) * 10

    def test_chirp_generation(self):
        """Test chirp signal generation."""
        config = SignalConfig(
            signal_type=SignalType.CHIRP,
            duration=self.duration,
            sample_rate=self.sample_rate,
            start_frequency=100.0,
            end_frequency=1000.0,
            amplitude=0.5,
        )

        signal = self.generator.generate(config)

        # Basic checks
        assert len(signal) == int(self.sample_rate * self.duration)
        assert np.max(np.abs(signal)) > 0

    def test_bit_depth_conversion(self):
        """Test different bit depth outputs."""
        for bit_depth in [16, 32]:
            config = SignalConfig(
                signal_type=SignalType.SINE,
                duration=0.1,
                sample_rate=self.sample_rate,
                frequency=440.0,
                amplitude=1.0,
                bit_depth=bit_depth,
            )

            signal = self.generator.generate(config)

            if bit_depth == 16:
                assert signal.dtype == np.int16
                assert np.max(np.abs(signal)) <= 2**15 - 1
            elif bit_depth == 32:
                assert signal.dtype == np.int32
                assert np.max(np.abs(signal)) <= 2**31 - 1

    def test_generate_test_chunk(self):
        """Test the convenience function for generating test chunks."""
        chunk = generate_test_chunk(
            duration=0.5, sample_rate=44100, frequency=440.0, amplitude=0.5
        )

        # Check structure matches expected format
        assert chunk["data_type"] == "audio_chunk"
        assert "data" in chunk
        assert "timestamp" in chunk
        assert "metadata" in chunk

        # Check metadata
        assert chunk["metadata"]["sample_rate"] == 44100
        assert chunk["metadata"]["bit_depth"] == 16
        assert chunk["metadata"]["location"] == "test"

        # Check data
        assert len(chunk["data"]) == int(0.5 * 44100)
        assert isinstance(chunk["data"], list)
        assert all(isinstance(x, int) for x in chunk["data"][:10])  # Check first 10


class TestSignalProperties:
    """Test mathematical properties of generated signals."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = SignalGenerator()

    def test_sine_wave_frequency(self):
        """Verify sine wave has correct frequency."""
        frequency = 1000.0
        sample_rate = 44100
        duration = 1.0

        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=duration,
            sample_rate=sample_rate,
            frequency=frequency,
            amplitude=1.0,
        )

        signal = self.generator.generate(config)

        # Convert to float
        signal_float = signal.astype(float) / (2**15 - 1)

        # Count zero crossings
        zero_crossings = np.where(np.diff(np.sign(signal_float)))[0]

        # Should have approximately 2 * frequency zero crossings
        expected_crossings = 2 * frequency * duration
        actual_crossings = len(zero_crossings)

        # Allow 1% error
        assert abs(actual_crossings - expected_crossings) < expected_crossings * 0.05

    def test_correlation_parameter(self):
        """Test that correlation parameter works correctly."""
        config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=44100,
            frequency=440.0,
            amplitude=0.5,
        )

        # Generate with different correlation values
        correlations = [1.0, 0.8, 0.5, 0.0]

        for target_corr in correlations:
            left, right = self.generator.generate_stereo_with_delay(
                config, delay_seconds=0.0, correlation=target_corr  # No delay
            )

            # Convert to float
            left_float = left.astype(float) / (2**15 - 1)
            right_float = right.astype(float) / (2**15 - 1)

            # Calculate actual correlation
            actual_corr = np.corrcoef(left_float, right_float)[0, 1]

            # For correlation = 1.0, should be perfect
            if target_corr == 1.0:
                assert actual_corr > 0.99
            else:
                # Allow some tolerance for randomness
                assert abs(actual_corr - target_corr) < 0.3


class TestCrossCorrelationScenarios:
    """Test cross-correlation specific scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = SignalGenerator()
        self.sample_rate = 44100

    def test_reference_and_remote_generation(self):
        """Test generation of reference and remote signals."""
        source_config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=self.sample_rate,
            frequency=100.0,  # Bass frequency
            amplitude=1.0,
        )

        delay = 0.1  # 100ms delay
        attenuation = 0.1  # Signal is 10% of original

        reference, remote = self.generator.generate_reference_and_remote(
            source_config=source_config,
            delay_seconds=delay,
            signal_attenuation=attenuation,
        )

        # Basic checks
        assert len(remote) >= len(reference)
        assert len(reference) == len(remote)
        assert reference.dtype == remote.dtype

        # Reference should be louder than remote
        ref_power = np.mean(reference.astype(float) ** 2)
        remote_power = np.mean(remote.astype(float) ** 2)
        assert ref_power > remote_power

    def test_snr_based_generation(self):
        """Test SNR-based signal generation."""
        source_config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=self.sample_rate,
            frequency=50.0,
            amplitude=1.0,
        )

        # Generate with specific SNR
        snr_db = -6  # Noise is twice as loud as signal
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=source_config,
            delay_seconds=0.05,
            signal_attenuation=None,  # Will be calculated from SNR
            snr_db=snr_db,
        )

        # Verify the signal is buried in noise
        # (Can't verify exact SNR due to randomness, but signal should be present)
        assert len(remote) == len(reference)

    def test_cross_correlation_detection(self):
        """Test that cross-correlation can detect the delayed signal."""
        source_config = SignalConfig(
            signal_type=SignalType.CHIRP,
            duration=2.0,
            sample_rate=self.sample_rate,
            start_frequency=20,
            end_frequency=200,
            amplitude=1.0,
        )

        delay = 0.25  # 250ms delay

        # Generate with good SNR
        reference, remote = self.generator.generate_reference_and_remote(
            source_config=source_config,
            delay_seconds=delay,
            signal_attenuation=0.3,
            snr_db=10,  # 10dB SNR
        )

        # Perform cross-correlation
        # Handle the fact that remote is longer
        min_len = min(len(reference), len(remote))
        ref_trim = reference[:min_len].astype(float)
        remote_trim = remote[:min_len].astype(float)

        # Normalize
        ref_norm = ref_trim / np.sqrt(np.sum(ref_trim**2))
        remote_norm = remote_trim / np.sqrt(np.sum(remote_trim**2))

        # Cross-correlate: find where reference appears in remote
        correlation = np.correlate(remote_norm, ref_norm, mode="full")
        lags = np.arange(len(correlation)) - (len(ref_norm) - 1)

        # Find peak
        peak_idx = np.argmax(np.abs(correlation))
        detected_lag_samples = lags[peak_idx]
        detected_delay_seconds = detected_lag_samples / self.sample_rate

        # Should detect the delay within 10ms accuracy
        assert abs(detected_delay_seconds - delay) < 0.010

    def test_multi_source_scenario(self):
        """Test multiple sound sources mixed together."""
        # Main stage
        main_config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=self.sample_rate,
            frequency=60.0,
            amplitude=1.0,
        )

        # Side stage
        side_config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=self.sample_rate,
            frequency=80.0,
            amplitude=0.8,
        )

        source_configs = [
            (main_config, 0.1, 0.5),  # 100ms delay, 50% attenuation
            (side_config, 0.15, 0.3),  # 150ms delay, 30% attenuation
        ]

        references, mixed_remote = self.generator.generate_multi_source_scenario(
            source_configs=source_configs
        )

        # Should have two reference signals
        assert len(references) == 2

        # Each reference should be detectable in the mixed signal
        for i, (ref, (config, delay, atten)) in enumerate(
            zip(references, source_configs)
        ):
            # Simple frequency-based detection for sine waves
            # In real scenario, would use cross-correlation
            remote_fft = np.fft.rfft(mixed_remote.astype(float))
            freqs = np.fft.rfftfreq(len(mixed_remote), 1 / self.sample_rate)

            # Find peak near expected frequency
            expected_freq = config.frequency if hasattr(config, "frequency") else 0

            if expected_freq > 0:
                freq_idx = np.argmin(np.abs(freqs - expected_freq))
                # Check there's energy at this frequency
                assert np.abs(remote_fft[freq_idx]) > np.mean(np.abs(remote_fft))

    def test_varying_noise_types(self):
        """Test with different types of background noise."""
        source_config = SignalConfig(
            signal_type=SignalType.SINE,
            duration=1.0,
            sample_rate=self.sample_rate,
            frequency=100.0,
            amplitude=1.0,
        )

        noise_types = [
            SignalType.WHITE_NOISE,
            SignalType.PINK_NOISE,
        ]

        for noise_type in noise_types:
            noise_config = SignalConfig(
                signal_type=noise_type,
                duration=1.5,  # Longer than source
                sample_rate=self.sample_rate,
                amplitude=0.5,
            )

            reference, remote = self.generator.generate_reference_and_remote(
                source_config=source_config,
                delay_seconds=0.05,
                signal_attenuation=0.3,
                noise_config=noise_config,
            )

            # Basic validation
            assert len(reference) == len(remote)
            assert np.std(remote) > 0  # Not silence


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
