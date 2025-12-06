#!/usr/bin/env python3
"""
Real-time Bass Limiter

Automatically limits bass levels based on remote measurements.
Runs on Raspberry Pi 4 with USB audio interface.

Hardware Setup:
    DJ Mixer → USB Audio In → Raspberry Pi → USB Audio Out → PA System

Software Requirements:
    pip install sounddevice redis numpy scipy

Usage:
    # Start Redis (on master node or locally)
    redis-server

    # Run limiter
    python realtime_bass_limiter.py --input-device 2 --output-device 3
"""

import argparse
import logging
import sys
import time
from collections import deque

import numpy as np
import redis
import sounddevice as sd
from scipy import signal

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class BassLimiter:
    """
    Real-time bass limiter with automatic gain control.

    Monitors remote bass levels via Redis and adjusts gain to keep
    bass below target threshold.
    """

    def __init__(
        self,
        sample_rate=48000,
        block_size=256,
        target_db=-20,
        max_db=-15,
        redis_host="localhost",
    ):
        """
        Args:
            sample_rate: Audio sample rate (Hz)
            block_size: Audio buffer size (samples)
            target_db: Target bass level (dBFS)
            max_db: Maximum allowed bass level (dBFS)
            redis_host: Redis server address
        """
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.target_db = target_db
        self.max_db = max_db

        # Connect to Redis
        try:
            self.redis = redis.Redis(host=redis_host, port=6379, decode_responses=True)
            self.redis.ping()
            logger.info(f"Connected to Redis at {redis_host}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            logger.warning("Running in standalone mode (no automatic control)")
            self.redis = None

        # Current gain (1.0 = no reduction)
        self.current_gain = 1.0

        # Gain smoothing (avoid clicks)
        self.gain_smooth_alpha = 0.01  # Smoothing factor

        # Statistics
        self.stats = {
            "samples_processed": 0,
            "gain_reductions": 0,
            "max_reduction_db": 0,
            "avg_remote_level": deque(maxlen=100),
        }

        # Safety
        self.last_measurement_time = 0
        self.measurement_timeout = 10.0  # seconds
        self.failsafe_mode = False

        logger.info(f"Bass Limiter initialized: target={target_db}dB, max={max_db}dB")

    def audio_callback(self, indata, outdata, frames, time_info, status):
        """Process audio in real-time (called by sounddevice)."""
        if status:
            logger.warning(f"Audio status: {status}")

        try:
            # Get latest remote bass level from Redis
            remote_bass_db = self.get_remote_bass_level()

            # Calculate required gain
            target_gain = self.calculate_gain(remote_bass_db)

            # Smooth gain changes to avoid clicks/pops
            self.current_gain = self.smooth_gain(self.current_gain, target_gain)

            # Apply gain to audio
            outdata[:] = indata * self.current_gain

            # Update statistics
            self.stats["samples_processed"] += frames

        except Exception as e:
            logger.error(f"Error in audio callback: {e}")
            # Failsafe: pass through unchanged
            outdata[:] = indata
            self.current_gain = 1.0

    def get_remote_bass_level(self):
        """
        Get latest bass level from remote nodes via Redis.

        Returns:
            float: Bass level in dBFS (or -100 if no data)
        """
        if self.redis is None:
            return -100  # No Redis, assume quiet

        try:
            # Get maximum bass level across all remote nodes
            max_level = self.redis.get("max_bass_level")

            if max_level is not None:
                level = float(max_level)
                self.last_measurement_time = time.time()
                self.stats["avg_remote_level"].append(level)
                self.failsafe_mode = False
                return level

        except Exception as e:
            logger.error(f"Error reading from Redis: {e}")

        # Check for timeout (no recent measurements)
        if time.time() - self.last_measurement_time > self.measurement_timeout:
            if not self.failsafe_mode:
                logger.warning("No recent measurements - entering failsafe mode")
                self.failsafe_mode = True

        return -100  # No data or timeout

    def calculate_gain(self, measured_db):
        """
        Calculate gain reduction based on measured bass level.

        Uses soft-knee compression:
        - Below target: no reduction
        - Near target: gentle reduction
        - Above max: hard limiting

        Args:
            measured_db: Measured bass level (dBFS)

        Returns:
            float: Linear gain (1.0 = no reduction, 0.5 = -6dB reduction)
        """
        if measured_db < self.target_db:
            # Below target: no limiting
            return 1.0

        elif measured_db > self.max_db:
            # Above maximum: hard limit
            excess_db = measured_db - self.max_db
            reduction_db = -excess_db
            gain = 10 ** (reduction_db / 20)

            # Update stats
            self.stats["gain_reductions"] += 1
            self.stats["max_reduction_db"] = max(
                self.stats["max_reduction_db"], abs(reduction_db)
            )

            logger.info(
                f"Hard limit: {measured_db:.1f}dB → reducing by {-reduction_db:.1f}dB"
            )
            return max(gain, 0.1)  # Never reduce below -20dB (0.1 = -20dB)

        else:
            # Between target and max: soft knee compression
            # Gentle slope to avoid abrupt changes
            knee_db = self.max_db - self.target_db
            position = (measured_db - self.target_db) / knee_db  # 0 to 1

            # Compression ratio increases with position
            # ratio = 1:1 at target, 10:1 at max
            ratio = 1 + position * 9

            # Calculate reduction
            excess_db = measured_db - self.target_db
            reduction_db = -(excess_db * (ratio - 1) / ratio)
            gain = 10 ** (reduction_db / 20)

            return gain

    def smooth_gain(self, current, target):
        """
        Exponentially smooth gain changes to avoid clicks.

        Args:
            current: Current gain
            target: Target gain

        Returns:
            float: Smoothed gain
        """
        # Exponential moving average
        return current + self.gain_smooth_alpha * (target - current)

    def get_stats(self):
        """Get limiter statistics."""
        avg_level = (
            np.mean(self.stats["avg_remote_level"])
            if self.stats["avg_remote_level"]
            else -100
        )

        return {
            "samples_processed": self.stats["samples_processed"],
            "time_processed_s": self.stats["samples_processed"] / self.sample_rate,
            "gain_reductions": self.stats["gain_reductions"],
            "max_reduction_db": self.stats["max_reduction_db"],
            "avg_remote_bass_db": avg_level,
            "current_gain_db": 20 * np.log10(self.current_gain),
            "failsafe_mode": self.failsafe_mode,
        }


def list_audio_devices():
    """List available audio devices."""
    print("\n=== Available Audio Devices ===")
    print(sd.query_devices())
    print()


def main():
    parser = argparse.ArgumentParser(description="Real-time Bass Limiter")
    parser.add_argument(
        "--input-device", type=int, help="Input device ID (see --list-devices)"
    )
    parser.add_argument("--output-device", type=int, help="Output device ID")
    parser.add_argument(
        "--sample-rate", type=int, default=48000, help="Sample rate (Hz)"
    )
    parser.add_argument(
        "--block-size", type=int, default=256, help="Block size (samples)"
    )
    parser.add_argument(
        "--target-db", type=float, default=-20, help="Target bass level (dBFS)"
    )
    parser.add_argument(
        "--max-db", type=float, default=-15, help="Maximum bass level (dBFS)"
    )
    parser.add_argument(
        "--redis-host", default="localhost", help="Redis server address"
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List audio devices and exit"
    )
    parser.add_argument(
        "--test-mode", action="store_true", help="Test without audio I/O"
    )

    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    # Create limiter
    limiter = BassLimiter(
        sample_rate=args.sample_rate,
        block_size=args.block_size,
        target_db=args.target_db,
        max_db=args.max_db,
        redis_host=args.redis_host,
    )

    if args.test_mode:
        logger.info("Running in test mode (no audio I/O)")
        try:
            while True:
                level = limiter.get_remote_bass_level()
                gain = limiter.calculate_gain(level)
                logger.info(f"Remote: {level:.1f}dB → Gain: {20*np.log10(gain):.1f}dB")
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopped")
        return

    # Configure audio stream
    logger.info("Starting audio stream...")
    logger.info(f"  Input device: {args.input_device}")
    logger.info(f"  Output device: {args.output_device}")
    logger.info(f"  Sample rate: {args.sample_rate} Hz")
    logger.info(f"  Block size: {args.block_size} samples")
    logger.info(f"  Latency: ~{args.block_size/args.sample_rate*1000:.1f}ms")

    try:
        with sd.Stream(
            device=(args.input_device, args.output_device),
            samplerate=args.sample_rate,
            blocksize=args.block_size,
            channels=2,  # Stereo
            dtype="float32",
            callback=limiter.audio_callback,
            latency="low",
        ):
            logger.info("Audio stream active - Press Ctrl+C to stop")
            logger.info("=" * 60)

            # Monitor and report stats
            while True:
                time.sleep(5)
                stats = limiter.get_stats()
                logger.info(
                    f"Stats: {stats['time_processed_s']:.0f}s processed, "
                    f"Remote: {stats['avg_remote_bass_db']:.1f}dB, "
                    f"Gain: {stats['current_gain_db']:.1f}dB, "
                    f"Reductions: {stats['gain_reductions']}, "
                    f"Max reduction: {stats['max_reduction_db']:.1f}dB"
                )

                if stats["failsafe_mode"]:
                    logger.warning("⚠️  FAILSAFE MODE - No recent measurements!")

    except KeyboardInterrupt:
        logger.info("\nStopping...")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()

    stats = limiter.get_stats()
    logger.info("=" * 60)
    logger.info("Final Statistics:")
    logger.info(f"  Total time: {stats['time_processed_s']:.1f}s")
    logger.info(f"  Gain reductions: {stats['gain_reductions']}")
    logger.info(f"  Max reduction: {stats['max_reduction_db']:.1f}dB")
    logger.info(f"  Avg remote bass: {stats['avg_remote_bass_db']:.1f}dB")


if __name__ == "__main__":
    main()
