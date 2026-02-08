#!/usr/bin/env python3
"""
Bass Sentry Microphone Calibration Utility

This script helps calibrate microphones to ensure accurate dB measurements
across all nodes in the system.

USAGE:
    1. Place a calibrated SPL meter next to the microphone
    2. Play pink noise or a reference tone at a known level (e.g., 94 dB)
    3. Run this script: python tools/calibrate.py
    4. Enter the reference level from your SPL meter when prompted
    5. Apply the calculated offset to your DAG configuration

REQUIREMENTS:
    - sounddevice (pip install sounddevice)
    - numpy (pip install numpy)
    - A calibrated SPL meter for reference
"""

import argparse
import sys
import time

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("Error: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)


def list_audio_devices():
    """List available audio input devices."""
    print("\nAvailable Audio Input Devices:")
    print("-" * 60)
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device["max_input_channels"] > 0:
            print(f"  [{i}] {device['name']}")
            print(f"      Channels: {device['max_input_channels']}, "
                  f"Sample Rate: {device['default_samplerate']:.0f} Hz")
    print()


def measure_level(duration: float = 10, sample_rate: int = 44100, device: int = None) -> float:
    """
    Record audio and calculate RMS level in dBFS.

    Args:
        duration: Recording duration in seconds
        sample_rate: Sample rate in Hz
        device: Audio device index (None for default)

    Returns:
        RMS level in dBFS
    """
    print(f"\nRecording for {duration} seconds...")
    print("Play your reference tone/noise now!")
    print()

    # Countdown
    for i in range(3, 0, -1):
        print(f"  Starting in {i}...")
        time.sleep(1)

    print("  Recording...")

    # Record audio
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype=np.float32,
        device=device,
    )
    sd.wait()

    print("  Done!")

    # Calculate RMS
    rms = np.sqrt(np.mean(audio ** 2))

    # Convert to dBFS (relative to full scale)
    # Full scale for float32 is 1.0
    if rms < 1e-10:
        print("\nWarning: Signal level very low. Check microphone connection.")
        return -100.0

    dbfs = 20 * np.log10(rms)

    return dbfs


def calculate_calibration(measured_dbfs: float, reference_db: float) -> float:
    """
    Calculate calibration offset.

    Args:
        measured_dbfs: Measured level in dBFS
        reference_db: Known reference level from SPL meter

    Returns:
        Calibration offset in dB
    """
    # The offset converts dBFS to dB SPL
    # dB SPL = dBFS + offset
    offset = reference_db - measured_dbfs
    return offset


def main():
    parser = argparse.ArgumentParser(
        description="Bass Sentry Microphone Calibration Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List audio devices
    python calibrate.py --list-devices

    # Calibrate with default settings (94 dB reference, 10s recording)
    python calibrate.py

    # Calibrate with specific device and reference level
    python calibrate.py --device 2 --reference 85 --duration 15

    # Quick calibration
    python calibrate.py --duration 5 --reference 94
        """,
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List available audio devices"
    )
    parser.add_argument(
        "--device", type=int, default=None, help="Audio device index"
    )
    parser.add_argument(
        "--duration", type=float, default=10, help="Recording duration in seconds"
    )
    parser.add_argument(
        "--reference", type=float, default=None,
        help="Reference SPL level (will prompt if not provided)"
    )
    parser.add_argument(
        "--sample-rate", type=int, default=44100, help="Sample rate in Hz"
    )

    args = parser.parse_args()

    # Header
    print("=" * 60)
    print("Bass Sentry Microphone Calibration")
    print("=" * 60)

    if args.list_devices:
        list_audio_devices()
        return

    # Show current device
    if args.device is not None:
        device_info = sd.query_devices(args.device)
        print(f"\nUsing device: [{args.device}] {device_info['name']}")
    else:
        default_device = sd.query_devices(kind="input")
        print(f"\nUsing default device: {default_device['name']}")

    # Get reference level
    if args.reference is None:
        print("\nPlace your calibrated SPL meter next to the microphone.")
        print("Play a reference tone (e.g., pink noise) at a known level.")
        reference_db = float(input("\nEnter the SPL meter reading (dB SPL): "))
    else:
        reference_db = args.reference
        print(f"\nUsing reference level: {reference_db} dB SPL")

    # Measure
    measured_dbfs = measure_level(
        duration=args.duration,
        sample_rate=args.sample_rate,
        device=args.device,
    )

    # Calculate offset
    offset = calculate_calibration(measured_dbfs, reference_db)

    # Results
    print("\n" + "=" * 60)
    print("CALIBRATION RESULTS")
    print("=" * 60)
    print(f"  Reference level:    {reference_db:.1f} dB SPL")
    print(f"  Measured level:     {measured_dbfs:.1f} dBFS")
    print(f"  Calibration offset: {offset:+.1f} dB")
    print("=" * 60)

    print("\nTo apply this calibration, add to your node config:")
    print(f"""
    "calibration": {{
        "offset_db": {offset:.1f}
    }}
""")

    print("Or update your DAG file processor settings with:")
    print(f'    "calibration_offset": {offset:.1f}')

    # Verification
    print("\n" + "-" * 60)
    print("VERIFICATION")
    print("-" * 60)
    print("After applying the offset, your measurements should read:")
    print(f"  {measured_dbfs:.1f} dBFS + {offset:+.1f} dB = {reference_db:.1f} dB SPL")
    print()

    # Offer to run again
    again = input("Run another measurement? (y/N): ").strip().lower()
    if again == "y":
        new_dbfs = measure_level(
            duration=args.duration,
            sample_rate=args.sample_rate,
            device=args.device,
        )
        corrected = new_dbfs + offset
        print(f"\n  Measured: {new_dbfs:.1f} dBFS")
        print(f"  Corrected: {corrected:.1f} dB SPL")


if __name__ == "__main__":
    main()
