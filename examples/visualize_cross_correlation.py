#!/usr/bin/env python3
# examples/visualize_cross_correlation.py
"""Visualize the cross-correlation problem Bass Sentry solves."""

import numpy as np
import matplotlib.pyplot as plt
from common.signals import SignalGenerator, SignalConfig, SignalType


def main():
    """Create a visual demonstration of cross-correlation."""
    generator = SignalGenerator()
    sample_rate = 44100

    # Create a distinctive bass signal (like from a DJ set)
    print("Generating bass-heavy test signal...")

    # Multi-tone bass signal
    bass_signal = generator.generate_multi_tone(
        frequencies=[40, 50, 63, 80],  # Common bass frequencies
        amplitudes=[0.4, 0.5, 0.3, 0.2],
        duration=2.0,
        sample_rate=sample_rate,
    )

    # Convert to config for the generator
    config = SignalConfig(
        signal_type=SignalType.SINE,  # Will be overridden
        duration=2.0,
        sample_rate=sample_rate,
        amplitude=1.0,
    )

    # Generate three scenarios
    scenarios = [
        ("Close (30m)", 0.087, 0.7, 25),  # 30m away, strong signal
        ("Medium (100m)", 0.291, 0.2, 10),  # 100m away, moderate signal
        ("Far (300m)", 0.874, 0.05, -5),  # 300m away, buried in noise
    ]

    # Create figure
    fig, axes = plt.subplots(len(scenarios) + 1, 2, figsize=(14, 12))
    fig.suptitle(
        "Bass Sentry: Detecting Event Audio at Different Distances", fontsize=16
    )

    # Plot reference signal
    time = np.arange(len(bass_signal)) / sample_rate
    axes[0, 0].plot(time, bass_signal / 32767, "b-", linewidth=2)
    axes[0, 0].set_title(
        "Reference Signal (at DJ Booth)", fontsize=12, fontweight="bold"
    )
    axes[0, 0].set_ylabel("Amplitude")
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].set_xlim(0, 0.5)  # Show first 500ms

    # Reference spectrum
    ref_fft = np.fft.rfft(bass_signal)
    ref_freqs = np.fft.rfftfreq(len(bass_signal), 1 / sample_rate)
    axes[0, 1].semilogy(ref_freqs[:500], np.abs(ref_fft[:500]), "b-", linewidth=2)
    axes[0, 1].set_title("Reference Spectrum", fontsize=12, fontweight="bold")
    axes[0, 1].set_xlabel("Frequency (Hz)")
    axes[0, 1].set_ylabel("Magnitude")
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].set_xlim(0, 200)  # Focus on bass frequencies

    # Process each scenario
    for i, (name, delay, atten, snr) in enumerate(scenarios):
        print(f"\nProcessing scenario: {name}")
        print(f"  Delay: {delay*1000:.1f}ms, Attenuation: {atten}, SNR: {snr}dB")

        # Generate remote signal
        reference, remote = generator.generate_reference_and_remote(
            source_config=config,
            delay_seconds=delay,
            signal_attenuation=atten,
            snr_db=snr,
        )

        # Override reference with our bass signal
        reference = bass_signal

        # Plot remote signal
        row = i + 1
        time_remote = np.arange(len(remote)) / sample_rate
        axes[row, 0].plot(time_remote, remote / 32767, "r-", alpha=0.7)
        axes[row, 0].set_title(
            f"{name}: Remote Signal (delay={delay*1000:.0f}ms, SNR={snr}dB)",
            fontsize=11,
        )
        axes[row, 0].set_ylabel("Amplitude")
        axes[row, 0].grid(True, alpha=0.3)
        axes[row, 0].set_xlim(0, 0.5)  # Show first 500ms

        # Add delay marker
        axes[row, 0].axvline(
            x=delay,
            color="g",
            linestyle="--",
            alpha=0.7,
            label=f"Expected: {delay*1000:.0f}ms",
        )

        # Calculate and plot cross-correlation
        ref_norm = reference.astype(float) / np.sqrt(
            np.sum(reference.astype(float) ** 2)
        )
        remote_norm = remote.astype(float) / np.sqrt(np.sum(remote.astype(float) ** 2))

        correlation = np.correlate(ref_norm, remote_norm, mode="full")
        lags = np.arange(-len(remote) + 1, len(reference))
        lag_time = lags / sample_rate

        # Find peak
        peak_idx = np.argmax(np.abs(correlation))
        detected_delay = lags[peak_idx] / sample_rate
        peak_value = correlation[peak_idx]

        # Plot correlation
        axes[row, 1].plot(lag_time * 1000, correlation, "g-")
        axes[row, 1].axvline(
            x=detected_delay * 1000,
            color="r",
            linestyle="-",
            label=f"Detected: {detected_delay*1000:.0f}ms",
        )
        axes[row, 1].axvline(
            x=delay * 1000,
            color="b",
            linestyle="--",
            alpha=0.5,
            label=f"Expected: {delay*1000:.0f}ms",
        )
        axes[row, 1].set_title(
            f"Cross-Correlation (peak={peak_value:.3f})", fontsize=11
        )
        axes[row, 1].set_xlabel("Lag (ms)")
        axes[row, 1].set_ylabel("Correlation")
        axes[row, 1].grid(True, alpha=0.3)
        axes[row, 1].legend(loc="upper right", fontsize=9)
        axes[row, 1].set_xlim(-100, 1000)

        # Print results
        error_ms = abs(detected_delay - delay) * 1000
        print(f"  Detected: {detected_delay*1000:.1f}ms (error: {error_ms:.1f}ms)")
        print(f"  Correlation peak: {peak_value:.3f}")

    # Add annotations
    axes[-1, 0].set_xlabel("Time (s)")
    axes[-1, 1].set_xlabel("Lag (ms)")

    # Add text explanation
    fig.text(
        0.1,
        0.02,
        "Bass Sentry uses cross-correlation to detect how long sound takes to travel from the event to remote locations.\n"
        "This allows precise volume adjustments while maintaining the energy of the event.",
        fontsize=10,
        style="italic",
        wrap=True,
    )

    plt.tight_layout()
    plt.subplots_adjust(top=0.94, bottom=0.08)
    plt.show()

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY: Cross-Correlation Performance")
    print("=" * 60)
    print("The signal generator successfully creates test scenarios showing:")
    print("- How signal strength decreases with distance")
    print("- How noise increases relative to signal (decreasing SNR)")
    print("- How cross-correlation can still detect delays even with weak signals")
    print("- The correlation peak value indicates detection confidence")
    print(
        "\nThis allows testing the cross-correlation algorithm without field recordings!"
    )


if __name__ == "__main__":
    main()
