#!/usr/bin/env python3
# examples/cross_correlation_demo.py
"""Example of using signal generator for cross-correlation testing.

This demonstrates the real Bass Sentry use case:
- Reference signal from the event (DJ mixer)
- Remote signal from across the street (delayed event audio + noise)
"""

import numpy as np
import matplotlib.pyplot as plt
from common.signals import SignalGenerator, SignalConfig, SignalType


def calculate_cross_correlation(reference, remote, sample_rate):
    """Calculate cross-correlation and find delay."""
    # Normalize signals
    ref_norm = reference.astype(float)
    ref_norm = ref_norm / np.sqrt(np.sum(ref_norm**2))

    remote_norm = remote.astype(float)
    remote_norm = remote_norm / np.sqrt(np.sum(remote_norm**2))

    # Calculate correlation
    correlation = np.correlate(ref_norm, remote_norm, mode="full")
    lags = np.arange(-len(remote) + 1, len(reference))

    # Find peak
    peak_idx = np.argmax(np.abs(correlation))
    peak_value = correlation[peak_idx]
    detected_lag = lags[peak_idx]
    detected_delay_ms = detected_lag / sample_rate * 1000

    return correlation, lags, detected_delay_ms, peak_value


def main():
    generator = SignalGenerator()
    sample_rate = 44100

    print("=== Bass Sentry Cross-Correlation Test ===\n")

    # Scenario 1: Clear signal with moderate noise
    print("Scenario 1: Outdoor event, 100m away")
    print("-" * 40)

    # Bass-heavy music signal
    source_config = SignalConfig(
        signal_type=SignalType.MULTI_TONE,  # Simulate bass-heavy music
        duration=5.0,
        sample_rate=sample_rate,
        amplitude=1.0,
    )

    # Generate multi-tone to simulate music
    music = generator.generate_multi_tone(
        frequencies=[40, 50, 60, 80, 100, 120],  # Bass frequencies
        amplitudes=[0.3, 0.4, 0.3, 0.2, 0.2, 0.1],
        duration=5.0,
        sample_rate=sample_rate,
    )

    # Create proper source config for the music
    source_config.signal_type = SignalType.SINE  # Dummy, we'll override

    # Sound travels ~343 m/s, so 100m = ~291ms delay
    delay_100m = 0.291

    # Generate reference and remote with 10dB SNR
    reference, remote = generator.generate_reference_and_remote(
        source_config=source_config,
        delay_seconds=delay_100m,
        signal_attenuation=0.1,  # Significant attenuation at distance
        snr_db=10,  # Decent SNR
    )

    # Override with our multi-tone music
    reference = music

    # Calculate cross-correlation
    corr, lags, delay_ms, peak = calculate_cross_correlation(
        reference, remote, sample_rate
    )

    print(f"Expected delay: {delay_100m*1000:.1f}ms")
    print(f"Detected delay: {delay_ms:.1f}ms")
    print(f"Error: {abs(delay_ms - delay_100m*1000):.1f}ms")
    print(f"Correlation peak: {peak:.3f}")
    print()

    # Scenario 2: Weak signal buried in noise
    print("Scenario 2: Indoor measurement, through walls")
    print("-" * 40)

    # Lower frequency content (better wall penetration)
    wall_config = SignalConfig(
        signal_type=SignalType.CHIRP,
        duration=3.0,
        sample_rate=sample_rate,
        start_frequency=20,
        end_frequency=100,
        amplitude=1.0,
    )

    delay_indoor = 0.05  # 50ms through building

    reference, remote = generator.generate_reference_and_remote(
        source_config=wall_config,
        delay_seconds=delay_indoor,
        signal_attenuation=0.01,  # Very weak signal
        snr_db=-10,  # Signal buried in noise
    )

    corr, lags, delay_ms, peak = calculate_cross_correlation(
        reference, remote, sample_rate
    )

    print(f"Expected delay: {delay_indoor*1000:.1f}ms")
    print(f"Detected delay: {delay_ms:.1f}ms")
    print(f"Error: {abs(delay_ms - delay_indoor*1000):.1f}ms")
    print(f"Correlation peak: {peak:.3f} (lower due to noise)")
    print()

    # Scenario 3: Multiple sound sources
    print("Scenario 3: Multiple stages at festival")
    print("-" * 40)

    # Main stage - loud bass
    main_config = SignalConfig(
        signal_type=SignalType.SINE,
        duration=2.0,
        sample_rate=sample_rate,
        frequency=50.0,
        amplitude=1.0,
    )

    # Side stage - different frequency
    side_config = SignalConfig(
        signal_type=SignalType.SINE,
        duration=2.0,
        sample_rate=sample_rate,
        frequency=75.0,
        amplitude=0.8,
    )

    # Delays from measurement point
    main_delay = 0.150  # 150ms from main stage
    side_delay = 0.080  # 80ms from side stage

    source_configs = [
        (main_config, main_delay, 0.4),  # Main stage
        (side_config, side_delay, 0.6),  # Side stage closer/louder
    ]

    references, mixed_remote = generator.generate_multi_source_scenario(
        source_configs=source_configs
    )

    # Try to detect main stage
    main_ref = references[0]
    corr, lags, delay_ms, peak = calculate_cross_correlation(
        main_ref, mixed_remote, sample_rate
    )

    print(f"Main stage expected delay: {main_delay*1000:.1f}ms")
    print(f"Main stage detected delay: {delay_ms:.1f}ms")
    print(f"Error: {abs(delay_ms - main_delay*1000):.1f}ms")
    print(f"Correlation peak: {peak:.3f}")
    print()

    # Scenario 4: Testing with pink noise (more realistic ambient)
    print("Scenario 4: Urban environment with pink noise")
    print("-" * 40)

    urban_config = SignalConfig(
        signal_type=SignalType.SINE,
        duration=4.0,
        sample_rate=sample_rate,
        frequency=63.0,  # Common problem frequency
        amplitude=1.0,
    )

    # Pink noise for urban environment
    noise_config = SignalConfig(
        signal_type=SignalType.PINK_NOISE,
        duration=4.5,
        sample_rate=sample_rate,
        amplitude=0.7,
    )

    delay_urban = 0.200  # 200ms

    reference, remote = generator.generate_reference_and_remote(
        source_config=urban_config,
        delay_seconds=delay_urban,
        signal_attenuation=0.15,
        noise_config=noise_config,
    )

    corr, lags, delay_ms, peak = calculate_cross_correlation(
        reference, remote, sample_rate
    )

    print(f"Expected delay: {delay_urban*1000:.1f}ms")
    print(f"Detected delay: {delay_ms:.1f}ms")
    print(f"Error: {abs(delay_ms - delay_urban*1000):.1f}ms")
    print(f"Correlation peak: {peak:.3f}")
    print()

    # Plot the last correlation for visualization
    if True:  # Set to True to see plots
        plt.figure(figsize=(12, 8))

        # Plot signals
        plt.subplot(3, 1, 1)
        time_ref = np.arange(len(reference)) / sample_rate
        plt.plot(time_ref, reference.astype(float) / 32767)
        plt.title("Reference Signal (from event)")
        plt.ylabel("Amplitude")
        plt.grid(True)

        plt.subplot(3, 1, 2)
        time_remote = np.arange(len(remote)) / sample_rate
        plt.plot(time_remote, remote.astype(float) / 32767, alpha=0.7)
        plt.title("Remote Signal (delayed + noise)")
        plt.ylabel("Amplitude")
        plt.grid(True)

        plt.subplot(3, 1, 3)
        lag_time_ms = lags / sample_rate * 1000
        plt.plot(lag_time_ms, correlation)
        plt.axvline(
            x=delay_ms, color="r", linestyle="--", label=f"Detected: {delay_ms:.1f}ms"
        )
        plt.axvline(
            x=delay_urban * 1000,
            color="g",
            linestyle="--",
            label=f"Expected: {delay_urban*1000:.1f}ms",
        )
        plt.title("Cross-Correlation")
        plt.xlabel("Lag (ms)")
        plt.ylabel("Correlation")
        plt.legend()
        plt.grid(True)

        plt.tight_layout()
        plt.show()

    print("\n=== Summary ===")
    print("The signal generator can create realistic test scenarios for:")
    print("- Different distances (delay)")
    print("- Different attenuations (signal strength)")
    print("- Different noise conditions (SNR)")
    print("- Multiple sound sources")
    print("\nThis enables testing the cross-correlation algorithm without")
    print("needing actual field recordings!")


if __name__ == "__main__":
    main()
