#!/usr/bin/env python3
# examples/signal_generator_demo.py
"""Example of using the signal generator for testing audio processing."""

import numpy as np
import matplotlib.pyplot as plt
from common.signals import SignalGenerator, SignalConfig, SignalType

# Create generator instance
generator = SignalGenerator()

# Example 1: Generate a simple test tone
print("Generating 440Hz test tone...")
config = SignalConfig(
    signal_type=SignalType.SINE,
    duration=1.0,
    sample_rate=44100,
    frequency=440.0,
    amplitude=0.5,
)
test_tone = generator.generate(config)
print(f"Generated {len(test_tone)} samples")

# Example 2: Generate stereo signals with delay for cross-correlation testing
print("\nGenerating stereo signals with 10ms delay...")
left, right = generator.generate_stereo_with_delay(
    config, delay_seconds=0.010, correlation=0.9  # 10ms delay  # 90% correlation
)

# Calculate cross-correlation
correlation = np.correlate(left, right, mode="full")
lag = np.arange(-len(right) + 1, len(left))
peak_idx = np.argmax(correlation)
peak_lag_samples = lag[peak_idx]
peak_lag_ms = peak_lag_samples / config.sample_rate * 1000

print(f"Cross-correlation peak at {peak_lag_ms:.1f}ms")

# Example 3: Generate multi-tone signal for frequency response testing
print("\nGenerating multi-tone signal...")
multi_tone = generator.generate_multi_tone(
    frequencies=[100, 250, 500, 1000, 2000],
    amplitudes=[0.2, 0.2, 0.2, 0.2, 0.2],
    duration=2.0,
)

# Example 4: Generate test chunk in the format expected by the system
print("\nGenerating test chunk for system testing...")
from common.signals import generate_test_chunk

chunk = generate_test_chunk(
    duration=0.5, sample_rate=44100, frequency=440.0, amplitude=0.5
)

print(f"Chunk structure:")
print(f"  - data_type: {chunk['data_type']}")
print(f"  - timestamp: {chunk['timestamp']}")
print(f"  - samples: {len(chunk['data'])}")
print(f"  - metadata: {chunk['metadata']}")

# Example 5: Generate different signal types for processor testing
print("\nGenerating various test signals...")

signal_types = [
    (SignalType.WHITE_NOISE, "White noise"),
    (SignalType.PINK_NOISE, "Pink noise"),
    (SignalType.CHIRP, "Frequency sweep"),
    (SignalType.IMPULSE, "Impulse response"),
]

for sig_type, name in signal_types:
    if sig_type == SignalType.CHIRP:
        config = SignalConfig(
            signal_type=sig_type,
            duration=2.0,
            sample_rate=44100,
            start_frequency=20,
            end_frequency=20000,
            amplitude=0.5,
        )
    else:
        config = SignalConfig(
            signal_type=sig_type, duration=1.0, sample_rate=44100, amplitude=0.5
        )

    signal = generator.generate(config)
    print(
        f"  - {name}: {len(signal)} samples, "
        f"range [{np.min(signal)}, {np.max(signal)}]"
    )

# Example 6: Test with bass frequencies for Bass Sentry
print("\nGenerating bass test signals...")

# Sub-bass sweep
bass_config = SignalConfig(
    signal_type=SignalType.CHIRP,
    duration=5.0,
    sample_rate=44100,
    start_frequency=20,
    end_frequency=85,
    amplitude=0.8,
)
bass_sweep = generator.generate(bass_config)

# Bass tone at problem frequency
bass_tone_config = SignalConfig(
    signal_type=SignalType.SINE,
    duration=2.0,
    sample_rate=44100,
    frequency=50.0,  # 50Hz is often problematic
    amplitude=0.8,
)
bass_tone = generator.generate(bass_tone_config)

print(f"  - Bass sweep: {len(bass_sweep)} samples")
print(f"  - 50Hz tone: {len(bass_tone)} samples")

print("\nDone! Signals ready for testing.")
