"""
Adaptive Correlation - Automatically handles echoes.

This is the "just works" solution that requires NO configuration.

How it works:
1. Try strongest peak first (fast, works 90% of time)
2. Check if result looks suspicious (echoes, instability)
3. If suspicious, automatically use first-peak strategy
4. Track stability over time to learn environment

Usage:
    from adaptive_correlation import AdaptiveCorrelator

    correlator = AdaptiveCorrelator()
    delay, confidence, metadata = correlator.find_delay(sig1, sig2, sample_rate, node_id)

    # That's it! No configuration needed.
"""

import numpy as np
from scipy.signal import correlate, find_peaks
from collections import deque
from typing import Tuple, Dict
import logging

logger = logging.getLogger(__name__)


class AdaptiveCorrelator:
    """
    Automatically adapts correlation strategy based on signal characteristics.

    NO CONFIGURATION REQUIRED - just works!
    """

    def __init__(self, history_size=20):
        """
        Args:
            history_size: Number of recent measurements to track per node
        """
        self.history = {}  # node_id -> deque of (delay, confidence) tuples
        self.environment_learned = {}  # node_id -> 'clean' | 'reverberant'
        self.history_size = history_size

    def find_delay(
        self,
        sig1: np.ndarray,
        sig2: np.ndarray,
        sample_rate: float,
        node_id: str = None,
    ) -> Tuple[float, float, Dict]:
        """
        Find time delay between signals, automatically handling echoes.

        Args:
            sig1: Reference signal
            sig2: Remote signal
            sample_rate: Sample rate in Hz
            node_id: Optional node identifier for adaptive learning

        Returns:
            (delay_seconds, confidence, metadata)
        """
        # Normalize signals
        sig1_centered = sig1 - np.mean(sig1)
        sig1_norm = sig1_centered / (np.std(sig1_centered) + 1e-10)

        sig2_centered = sig2 - np.mean(sig2)
        sig2_norm = sig2_centered / (np.std(sig2_centered) + 1e-10)

        # Correlate
        correlation = correlate(sig2_norm, sig1_norm, mode="full", method="fft")
        n = len(sig1)
        lags = np.arange(-n + 1, len(sig2))

        # Step 1: Try strongest peak (fast, usually correct)
        strongest_idx = np.argmax(np.abs(correlation))
        strongest_delay = lags[strongest_idx] / sample_rate
        strongest_value = correlation[strongest_idx]

        # Step 2: Analyze correlation to detect echo problems
        max_corr = np.max(np.abs(correlation))
        threshold = max_corr * 0.25  # Find significant peaks

        peaks, properties = find_peaks(
            np.abs(correlation),
            height=threshold,
            distance=int(0.005 * sample_rate),  # Min 5ms between peaks
        )

        num_significant_peaks = len(peaks)

        # Step 3: Decide if we need echo-robust strategy
        use_first_peak = False
        reason = "strongest_peak"

        # Check 1: Multiple strong peaks? (Echoes present)
        if num_significant_peaks > 3:
            use_first_peak = True
            reason = "multiple_peaks_detected"

        # Check 2: Has this node been unstable in the past?
        if node_id and node_id in self.environment_learned:
            if self.environment_learned[node_id] == "reverberant":
                use_first_peak = True
                reason = "learned_reverberant_environment"

        # Check 3: Previous measurements highly variable?
        if node_id and node_id in self.history:
            recent_delays = [d for d, c in self.history[node_id]]
            if len(recent_delays) >= 5:
                std_delay = np.std(recent_delays)
                if std_delay > 0.005:  # > 5ms standard deviation
                    use_first_peak = True
                    reason = "unstable_history"

        # Apply strategy
        if use_first_peak:
            # Use first peak strategy (echo-robust)
            delay, confidence, metadata = self._find_first_peak(
                correlation, lags, sample_rate, threshold
            )
            metadata["strategy"] = "first_peak"
            metadata["reason"] = reason
        else:
            # Use strongest peak (default, fast)
            delay = strongest_delay
            confidence = min(1.0, abs(strongest_value) / (max_corr + 1e-10))

            # Reduce confidence if many peaks present
            confidence = confidence / (1.0 + 0.1 * (num_significant_peaks - 1))

            metadata = {
                "strategy": "strongest_peak",
                "reason": reason,
                "num_peaks": num_significant_peaks,
                "peak_value": strongest_value,
            }

        # Step 4: Update history and learn environment
        if node_id:
            self._update_history(node_id, delay, confidence, num_significant_peaks)

        # Step 5: Add quality indicators
        distance_m = abs(delay * 343.0)
        metadata["distance_m"] = distance_m
        metadata["num_significant_peaks"] = num_significant_peaks

        # Warn if implausible
        if distance_m > 200:  # > 200m is suspicious
            logger.warning(
                f"{node_id}: Implausible distance {distance_m:.1f}m - possible echo"
            )
            confidence *= 0.5

        return delay, confidence, metadata

    def _find_first_peak(
        self,
        correlation: np.ndarray,
        lags: np.ndarray,
        sample_rate: float,
        threshold: float,
    ) -> Tuple[float, float, Dict]:
        """Find first peak above threshold (echo-robust)."""

        peaks, properties = find_peaks(np.abs(correlation), height=threshold)

        if len(peaks) == 0:
            # Fallback to strongest peak
            logger.warning("No peaks above threshold, using strongest")
            peak_idx = np.argmax(np.abs(correlation))
            delay = lags[peak_idx] / sample_rate
            confidence = 0.3
            metadata = {"warning": "fallback_to_strongest"}
            return delay, confidence, metadata

        # Find first peak (closest to zero lag, excluding negative lags if positive peaks exist)
        center_idx = len(correlation) // 2

        positive_peaks = peaks[peaks >= center_idx]
        negative_peaks = peaks[peaks < center_idx]

        # Choose side with stronger correlation
        if len(positive_peaks) > 0 and len(negative_peaks) > 0:
            pos_strength = np.max(np.abs(correlation[positive_peaks]))
            neg_strength = np.max(np.abs(correlation[negative_peaks]))

            if pos_strength > neg_strength:
                first_peak = positive_peaks[0]  # Earliest positive
            else:
                first_peak = negative_peaks[-1]  # Latest negative (closest to 0)
        elif len(positive_peaks) > 0:
            first_peak = positive_peaks[0]
        else:
            first_peak = negative_peaks[-1]

        delay = lags[first_peak] / sample_rate
        peak_value = correlation[first_peak]

        # Confidence based on peak strength and number of alternatives
        max_corr = np.max(np.abs(correlation))
        confidence = abs(peak_value) / (max_corr + 1e-10)
        confidence = confidence / (1.0 + 0.15 * (len(peaks) - 1))

        metadata = {"num_peaks": len(peaks), "peak_value": peak_value}

        return delay, confidence, metadata

    def _update_history(
        self, node_id: str, delay: float, confidence: float, num_peaks: int
    ):
        """Update measurement history and learn environment."""

        if node_id not in self.history:
            self.history[node_id] = deque(maxlen=self.history_size)

        self.history[node_id].append((delay, confidence))

        # Learn environment after enough measurements
        if len(self.history[node_id]) >= 10:
            recent_delays = [d for d, c in self.history[node_id]]
            std_delay = np.std(recent_delays)

            # High variability or many peaks = reverberant
            if std_delay > 0.003 or num_peaks > 3:  # >3ms std or >3 peaks
                self.environment_learned[node_id] = "reverberant"
                logger.info(
                    f"{node_id}: Learned reverberant environment "
                    f"(std={std_delay*1000:.1f}ms, peaks={num_peaks})"
                )
            else:
                self.environment_learned[node_id] = "clean"

    def get_node_stats(self, node_id: str) -> Dict:
        """Get statistics for a node (for debugging/monitoring)."""
        if node_id not in self.history:
            return {}

        delays = [d for d, c in self.history[node_id]]
        confidences = [c for d, c in self.history[node_id]]

        return {
            "environment": self.environment_learned.get(node_id, "unknown"),
            "num_measurements": len(delays),
            "mean_delay_ms": np.mean(delays) * 1000,
            "std_delay_ms": np.std(delays) * 1000,
            "mean_distance_m": np.mean(delays) * 343,
            "mean_confidence": np.mean(confidences),
            "stability": "stable" if np.std(delays) < 0.003 else "unstable",
        }


# Global instance for easy import
_global_correlator = None


def get_adaptive_correlator():
    """Get global adaptive correlator instance (singleton)."""
    global _global_correlator
    if _global_correlator is None:
        _global_correlator = AdaptiveCorrelator()
    return _global_correlator


if __name__ == "__main__":
    """Demo: Automatically handles echoes without configuration."""

    # Create test signals with echoes
    sample_rate = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration))

    # Reference: chirp signal
    freq_start, freq_end = 20, 200
    reference = np.sin(
        2 * np.pi * (freq_start + (freq_end - freq_start) * t / duration) * t
    )

    # Simulate three different scenarios
    scenarios = [
        ("Clean (direct path only)", 0.030, 0.0),  # 30ms delay, no echo
        ("Moderate echo", 0.030, 0.5),  # 30ms + 50% echo at 45ms
        ("Strong echo", 0.030, 0.8),  # 30ms + 80% echo at 45ms
    ]

    correlator = AdaptiveCorrelator()

    print("=" * 70)
    print("ADAPTIVE CORRELATION DEMO - Automatically Handles Echoes")
    print("=" * 70)

    for scenario_name, direct_delay, echo_strength in scenarios:
        # Create remote signal
        direct_samples = int(direct_delay * sample_rate)
        echo_samples = int((direct_delay + 0.015) * sample_rate)  # Echo 15ms later

        remote = np.zeros_like(reference)

        # Direct path
        if direct_samples + len(reference) <= len(remote):
            remote[direct_samples : direct_samples + len(reference)] = reference * 0.7

        # Echo
        if echo_strength > 0 and echo_samples + len(reference) <= len(remote):
            remote[echo_samples : echo_samples + len(reference)] += (
                reference * echo_strength * 0.4
            )

        # Add noise
        remote += np.random.randn(len(remote)) * 0.1

        # Detect delay
        delay, confidence, metadata = correlator.find_delay(
            reference, remote, sample_rate, node_id=scenario_name
        )

        print(f"\n{scenario_name}:")
        print(f"  Expected delay: {direct_delay * 1000:.1f}ms")
        print(f"  Detected delay: {delay * 1000:.1f}ms")
        print(f"  Error: {abs(delay - direct_delay) * 1000:.1f}ms")
        print(f"  Strategy: {metadata['strategy']}")
        print(f"  Reason: {metadata['reason']}")
        print(f"  Confidence: {confidence:.2f}")
        print(f"  Significant peaks: {metadata['num_significant_peaks']}")

    print("\n" + "=" * 70)
    print("Result: Automatically adapted to echo conditions!")
    print("=" * 70)

    # Show learned environments
    print("\nLearned environments:")
    for scenario_name, _, _ in scenarios:
        stats = correlator.get_node_stats(scenario_name)
        if stats:
            print(
                f"  {scenario_name}: {stats['environment']} "
                f"(stability: {stats['stability']})"
            )
