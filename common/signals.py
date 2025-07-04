# bass_sentry/common/signals.py
"""Signal generator for testing audio processing pipelines."""

import numpy as np
from typing import Optional, Tuple, Union, List
from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    """Available signal types for generation."""

    SINE = "sine"
    WHITE_NOISE = "white_noise"
    PINK_NOISE = "pink_noise"
    SQUARE = "square"
    SAWTOOTH = "sawtooth"
    CHIRP = "chirp"
    IMPULSE = "impulse"
    SILENCE = "silence"


@dataclass
class SignalConfig:
    """Configuration for signal generation."""

    signal_type: SignalType
    duration: float  # seconds
    sample_rate: int = 44100
    frequency: Optional[float] = None  # Hz, for periodic signals
    amplitude: float = 0.5  # 0-1 range
    bit_depth: int = 16

    # For chirp signals
    start_frequency: Optional[float] = None
    end_frequency: Optional[float] = None

    # For impulse signals
    impulse_time: Optional[float] = None  # Time of impulse in seconds


class SignalGenerator:
    """Generate test signals for audio processing."""

    def __init__(self):
        self._pink_noise_state = None

    def generate(self, config: SignalConfig) -> np.ndarray:
        """Generate a signal based on configuration.

        Returns:
            np.ndarray: Audio samples in int16 format
        """
        # Calculate number of samples
        num_samples = int(config.duration * config.sample_rate)

        # Generate the signal
        if config.signal_type == SignalType.SINE:
            signal = self._generate_sine(num_samples, config)
        elif config.signal_type == SignalType.WHITE_NOISE:
            signal = self._generate_white_noise(num_samples, config)
        elif config.signal_type == SignalType.PINK_NOISE:
            signal = self._generate_pink_noise(num_samples, config)
        elif config.signal_type == SignalType.SQUARE:
            signal = self._generate_square(num_samples, config)
        elif config.signal_type == SignalType.SAWTOOTH:
            signal = self._generate_sawtooth(num_samples, config)
        elif config.signal_type == SignalType.CHIRP:
            signal = self._generate_chirp(num_samples, config)
        elif config.signal_type == SignalType.IMPULSE:
            signal = self._generate_impulse(num_samples, config)
        elif config.signal_type == SignalType.SILENCE:
            signal = np.zeros(num_samples)
        else:
            raise ValueError(f"Unknown signal type: {config.signal_type}")

        # Apply amplitude scaling
        signal = signal * config.amplitude

        # Convert to appropriate bit depth
        return self._convert_to_int(signal, config.bit_depth)

    def generate_stereo_with_delay(
        self, config: SignalConfig, delay_seconds: float, correlation: float = 1.0
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generate two correlated signals with a time delay.

        Args:
            config: Signal configuration
            delay_seconds: Delay between channels (positive = right delayed)
            correlation: Correlation coefficient (0-1), 1 = identical signals

        Returns:
            Tuple of (left_channel, right_channel) as int16 arrays
        """
        # Generate base signal
        base_signal = self.generate(config)

        # Calculate delay in samples
        delay_samples = int(abs(delay_seconds) * config.sample_rate)

        # Create delayed version
        if delay_samples > 0:
            # Create arrays of the same length
            left = np.zeros_like(base_signal)
            right = np.zeros_like(base_signal)

            if delay_seconds > 0:
                # Right channel delayed - left starts immediately, right starts later
                left[:] = base_signal
                if delay_samples < len(base_signal):
                    right[delay_samples:] = base_signal[:-delay_samples]
            else:
                # Left channel delayed - right starts immediately, left starts later
                right[:] = base_signal
                if delay_samples < len(base_signal):
                    left[delay_samples:] = base_signal[:-delay_samples]
        else:
            # No delay
            left = base_signal.copy()
            right = base_signal.copy()

        # Add uncorrelated noise to reduce correlation if needed
        if correlation < 1.0:
            # Use a more accurate formula for mixing
            signal_weight = np.sqrt(correlation)
            noise_weight = np.sqrt(1 - correlation)

            noise_config = SignalConfig(
                signal_type=SignalType.WHITE_NOISE,
                duration=config.duration,
                sample_rate=config.sample_rate,
                amplitude=config.amplitude,
                bit_depth=config.bit_depth,
            )
            noise = self.generate(noise_config)

            # Mix with proper weights (apply to the delayed channel)
            if delay_seconds >= 0:
                right = (signal_weight * right + noise_weight * noise).astype(
                    right.dtype
                )
            else:
                left = (signal_weight * left + noise_weight * noise).astype(left.dtype)

        return left, right

    def generate_reference_and_remote(
        self,
        source_config: SignalConfig,
        delay_seconds: float,
        signal_attenuation: float,
        noise_config: Optional[SignalConfig] = None,
        snr_db: Optional[float] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generate reference and remote signals for cross-correlation testing.

        This simulates the real-world scenario where:
        - Reference signal: Clean source audio (e.g., from the DJ mixer)
        - Remote signal: Delayed, attenuated source + environmental noise

        Args:
            source_config: Configuration for the source signal
            delay_seconds: Delay of source signal at remote location
            signal_attenuation: Attenuation factor for source (0-1)
            noise_config: Configuration for noise (if None, uses white noise)
            snr_db: Signal-to-noise ratio in dB (alternative to signal_attenuation)
                   If provided, overrides signal_attenuation

        Returns:
            Tuple of (reference_signal, remote_signal) as int16 arrays
        """
        # Generate reference signal (clean source)
        reference = self.generate(source_config)

        # Calculate delay in samples
        delay_samples = int(delay_seconds * source_config.sample_rate)

        # Create delayed and attenuated version
        if delay_samples > 0:
            # Pad with zeros at the beginning for delay
            delayed_source = np.concatenate(
                [np.zeros(delay_samples, dtype=reference.dtype), reference]
            )
        else:
            delayed_source = reference.copy()

        # Convert to float for mixing
        delayed_source_float = delayed_source.astype(float) / (
            2 ** (source_config.bit_depth - 1) - 1
        )

        # Generate or configure noise
        if noise_config is None:
            noise_config = SignalConfig(
                signal_type=SignalType.WHITE_NOISE,
                duration=source_config.duration + delay_seconds,
                sample_rate=source_config.sample_rate,
                amplitude=1.0,
                bit_depth=source_config.bit_depth,
            )
        else:
            # Ensure noise is long enough
            noise_config.duration = source_config.duration + delay_seconds

        noise = self.generate(noise_config)
        noise_float = noise.astype(float) / (2 ** (noise_config.bit_depth - 1) - 1)

        # Trim noise to match delayed source length
        noise_float = noise_float[: len(delayed_source_float)]

        # Calculate attenuation based on SNR if provided
        if snr_db is not None:
            # SNR = 20 * log10(signal_rms / noise_rms)
            # signal_rms / noise_rms = 10^(SNR/20)
            signal_rms = np.sqrt(np.mean(delayed_source_float**2))
            noise_rms = np.sqrt(np.mean(noise_float**2))

            if noise_rms > 0:
                desired_signal_rms = noise_rms * (10 ** (snr_db / 20))
                signal_attenuation = (
                    desired_signal_rms / signal_rms if signal_rms > 0 else 0
                )
            else:
                signal_attenuation = 1.0

        # Apply attenuation to delayed source
        attenuated_source = delayed_source_float * signal_attenuation

        # Mix signal and noise
        remote_signal_float = attenuated_source + noise_float * noise_config.amplitude

        # Normalize to prevent clipping
        max_val = np.max(np.abs(remote_signal_float))
        if max_val > 1.0:
            remote_signal_float = remote_signal_float / max_val

        # Convert back to integer
        remote_signal = self._convert_to_int(
            remote_signal_float, source_config.bit_depth
        )

        # Trim remote signal to match reference length (for easier testing)
        # In real scenario, remote might be longer
        remote_signal = remote_signal[: len(reference)]

        return reference, remote_signal

    def generate_multi_source_scenario(
        self,
        source_configs: List[Tuple[SignalConfig, float, float]],
        noise_config: Optional[SignalConfig] = None,
        duration: Optional[float] = None,
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """Generate multiple reference signals and a mixed remote signal.

        Simulates multiple sound sources (e.g., main stage + side stage)
        captured at a remote location.

        Args:
            source_configs: List of (config, delay, attenuation) tuples
            noise_config: Configuration for background noise
            duration: Total duration (uses max of all sources if None)

        Returns:
            Tuple of (reference_signals_list, mixed_remote_signal)
        """
        references = []
        delayed_sources = []
        max_length = 0

        # Generate all source signals
        for config, delay, attenuation in source_configs:
            # Generate reference
            ref = self.generate(config)
            references.append(ref)

            # Create delayed version
            delay_samples = int(delay * config.sample_rate)
            if delay_samples > 0:
                delayed = np.concatenate(
                    [np.zeros(delay_samples, dtype=ref.dtype), ref]
                )
            else:
                delayed = ref.copy()

            # Convert to float and attenuate
            delayed_float = delayed.astype(float) / (2 ** (config.bit_depth - 1) - 1)
            delayed_float *= attenuation

            delayed_sources.append(delayed_float)
            max_length = max(max_length, len(delayed_float))

        # Pad all delayed sources to same length
        for i in range(len(delayed_sources)):
            if len(delayed_sources[i]) < max_length:
                delayed_sources[i] = np.pad(
                    delayed_sources[i], (0, max_length - len(delayed_sources[i]))
                )

        # Generate noise
        if noise_config is None:
            noise_duration = max_length / source_configs[0][0].sample_rate
            noise_config = SignalConfig(
                signal_type=SignalType.WHITE_NOISE,
                duration=noise_duration,
                sample_rate=source_configs[0][0].sample_rate,
                amplitude=0.3,
                bit_depth=source_configs[0][0].bit_depth,
            )

        noise = self.generate(noise_config)
        noise_float = noise.astype(float) / (2 ** (noise_config.bit_depth - 1) - 1)
        noise_float = noise_float[:max_length]

        # Ensure noise is exactly the right length
        if len(noise_float) < max_length:
            noise_float = np.pad(noise_float, (0, max_length - len(noise_float)))
        else:
            noise_float = noise_float[:max_length]

        # Mix all sources and noise
        mixed = np.sum(delayed_sources, axis=0) + noise_float

        # Normalize
        max_val = np.max(np.abs(mixed))
        if max_val > 1.0:
            mixed = mixed / max_val

        # Convert to integer
        remote_signal = self._convert_to_int(mixed, source_configs[0][0].bit_depth)

        return references, remote_signal

    def generate_multi_tone(
        self,
        frequencies: List[float],
        amplitudes: List[float],
        duration: float,
        sample_rate: int = 44100,
        bit_depth: int = 16,
    ) -> np.ndarray:
        """Generate a signal with multiple frequency components.

        Args:
            frequencies: List of frequencies in Hz
            amplitudes: List of amplitudes (0-1) for each frequency
            duration: Duration in seconds
            sample_rate: Sample rate in Hz
            bit_depth: Bit depth for output

        Returns:
            np.ndarray: Combined signal as int16 array
        """
        if len(frequencies) != len(amplitudes):
            raise ValueError("Frequencies and amplitudes must have same length")

        num_samples = int(duration * sample_rate)
        t = np.linspace(0, duration, num_samples, endpoint=False)

        signal = np.zeros(num_samples)
        for freq, amp in zip(frequencies, amplitudes):
            signal += amp * np.sin(2 * np.pi * freq * t)

        # Normalize to prevent clipping
        max_amp = np.sum(amplitudes)
        if max_amp > 1.0:
            signal = signal / max_amp

        return self._convert_to_int(signal, bit_depth)

    def _generate_sine(self, num_samples: int, config: SignalConfig) -> np.ndarray:
        """Generate a sine wave."""
        if config.frequency is None:
            raise ValueError("Frequency required for sine wave")

        t = np.linspace(0, config.duration, num_samples, endpoint=False)
        return np.sin(2 * np.pi * config.frequency * t)

    def _generate_white_noise(
        self, num_samples: int, config: SignalConfig
    ) -> np.ndarray:
        """Generate white noise."""
        return np.random.randn(num_samples)

    def _generate_pink_noise(
        self, num_samples: int, config: SignalConfig
    ) -> np.ndarray:
        """Generate pink noise using the Voss-McCartney algorithm."""
        # Number of random sources (more = better approximation)
        n_rows = 16

        # Initialize array
        array = np.empty((n_rows, num_samples))
        array.fill(np.nan)
        array[0, :] = np.random.randn(num_samples)

        # Fill the array
        for i in range(1, n_rows):
            stride = 2**i
            for j in range(0, num_samples, stride):
                array[i, j] = np.random.randn()

        # Interpolate missing values
        for i in range(1, n_rows):
            mask = np.isnan(array[i, :])
            array[i, mask] = np.interp(
                np.where(mask)[0], np.where(~mask)[0], array[i, ~mask]
            )

        # Sum and normalize
        pink = np.sum(array, axis=0)
        pink = pink / np.sqrt(n_rows)

        return pink

    def _generate_square(self, num_samples: int, config: SignalConfig) -> np.ndarray:
        """Generate a square wave."""
        if config.frequency is None:
            raise ValueError("Frequency required for square wave")

        t = np.linspace(0, config.duration, num_samples, endpoint=False)
        return np.sign(np.sin(2 * np.pi * config.frequency * t))

    def _generate_sawtooth(self, num_samples: int, config: SignalConfig) -> np.ndarray:
        """Generate a sawtooth wave."""
        if config.frequency is None:
            raise ValueError("Frequency required for sawtooth wave")

        t = np.linspace(0, config.duration, num_samples, endpoint=False)
        return 2 * (config.frequency * t % 1) - 1

    def _generate_chirp(self, num_samples: int, config: SignalConfig) -> np.ndarray:
        """Generate a linear chirp (frequency sweep)."""
        if config.start_frequency is None or config.end_frequency is None:
            raise ValueError("Start and end frequencies required for chirp")

        t = np.linspace(0, config.duration, num_samples, endpoint=False)
        phase = (
            2
            * np.pi
            * (
                config.start_frequency * t
                + (config.end_frequency - config.start_frequency)
                * t**2
                / (2 * config.duration)
            )
        )
        return np.sin(phase)

    def _generate_impulse(self, num_samples: int, config: SignalConfig) -> np.ndarray:
        """Generate an impulse signal."""
        signal = np.zeros(num_samples)

        # Place impulse at specified time or center
        if config.impulse_time is not None:
            impulse_sample = int(config.impulse_time * config.sample_rate)
        else:
            impulse_sample = num_samples // 2

        if 0 <= impulse_sample < num_samples:
            signal[impulse_sample] = 1.0

        return signal

    def _convert_to_int(self, signal: np.ndarray, bit_depth: int) -> np.ndarray:
        """Convert normalized float signal to integer format."""
        # Clip to prevent overflow
        signal = np.clip(signal, -1.0, 1.0)

        # Scale to bit depth
        if bit_depth == 16:
            max_val = 2**15 - 1
            return (signal * max_val).astype(np.int16)
        elif bit_depth == 32:
            max_val = 2**31 - 1
            return (signal * max_val).astype(np.int32)
        else:
            raise ValueError(f"Unsupported bit depth: {bit_depth}")


# Convenience functions
def generate_test_chunk(
    duration: float = 0.5,
    sample_rate: int = 44100,
    frequency: float = 440.0,
    amplitude: float = 0.5,
) -> dict:
    """Generate a test audio chunk matching the expected data format.

    Returns:
        dict: Data structure matching the remote node format
    """
    generator = SignalGenerator()
    config = SignalConfig(
        signal_type=SignalType.SINE,
        duration=duration,
        sample_rate=sample_rate,
        frequency=frequency,
        amplitude=amplitude,
        bit_depth=16,
    )

    audio_data = generator.generate(config)

    return {
        "data_type": "audio_chunk",
        "data": audio_data.tolist(),
        "timestamp": int(1e9),  # Fixed timestamp for testing
        "time_precision": "ns",
        "metadata": {"sample_rate": sample_rate, "bit_depth": 16, "location": "test"},
    }
