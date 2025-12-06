"""
Enhanced correlation with echo handling strategies.

Provides multiple peak detection strategies for different environments:
1. Strongest peak (current default)
2. First peak above threshold (best for distance)
3. Multi-peak analysis (detects echoes)
4. Windowed search (rejects distant echoes)
"""

import numpy as np
from scipy.signal import correlate, find_peaks
from typing import Tuple, List, Dict
import logging

logger = logging.getLogger(__name__)


class CorrelationStrategy:
    """Base class for correlation peak detection strategies."""

    def find_peak(
        self, correlation: np.ndarray, lags: np.ndarray, sample_rate: float
    ) -> Tuple[int, float, Dict]:
        """
        Find the primary peak in correlation function.

        Returns:
            (peak_index, delay_seconds, metadata)
        """
        raise NotImplementedError


class StrongestPeakStrategy(CorrelationStrategy):
    """Current default: Find strongest peak (works for most cases)."""

    def find_peak(
        self, correlation: np.ndarray, lags: np.ndarray, sample_rate: float
    ) -> Tuple[int, float, Dict]:

        peak_idx = np.argmax(np.abs(correlation))
        delay = lags[peak_idx] / sample_rate

        metadata = {
            "strategy": "strongest_peak",
            "peak_value": correlation[peak_idx],
            "confidence": 1.0,  # High confidence if single strong peak
        }

        return peak_idx, delay, metadata


class FirstPeakStrategy(CorrelationStrategy):
    """
    Find FIRST peak above threshold.

    Best for distance measurement when echoes present:
    - Direct path always arrives first
    - Echoes arrive later (longer path length)

    Use when:
    - Distance accuracy is critical
    - Environment is reverberant
    - Echoes might be stronger than direct path
    """

    def __init__(self, threshold_ratio=0.3, min_peak_height=None):
        """
        Args:
            threshold_ratio: Fraction of max correlation to use as threshold
            min_peak_height: Absolute minimum correlation value
        """
        self.threshold_ratio = threshold_ratio
        self.min_peak_height = min_peak_height

    def find_peak(
        self, correlation: np.ndarray, lags: np.ndarray, sample_rate: float
    ) -> Tuple[int, float, Dict]:

        # Calculate threshold
        max_corr = np.max(np.abs(correlation))
        threshold = max_corr * self.threshold_ratio

        if self.min_peak_height is not None:
            threshold = max(threshold, self.min_peak_height)

        # Find all peaks above threshold
        peaks, properties = find_peaks(np.abs(correlation), height=threshold)

        if len(peaks) == 0:
            logger.warning(f"No peaks above threshold {threshold:.2f}")
            # Fallback to strongest peak
            peak_idx = np.argmax(np.abs(correlation))
            delay = lags[peak_idx] / sample_rate

            metadata = {
                "strategy": "first_peak_fallback",
                "peak_value": correlation[peak_idx],
                "confidence": 0.3,  # Low confidence
                "warning": "No peaks above threshold, used strongest",
            }
            return peak_idx, delay, metadata

        # Find FIRST peak (shortest delay, assuming centered at 0)
        center_idx = len(correlation) // 2

        # Separate into negative lags (remote before reference) and positive lags
        positive_peaks = peaks[peaks >= center_idx]
        negative_peaks = peaks[peaks < center_idx]

        # Choose based on which side has stronger correlation
        if len(positive_peaks) > 0 and len(negative_peaks) > 0:
            pos_strength = np.max(np.abs(correlation[positive_peaks]))
            neg_strength = np.max(np.abs(correlation[negative_peaks]))

            if pos_strength > neg_strength:
                first_peak = positive_peaks[0]  # Earliest positive lag
            else:
                first_peak = negative_peaks[-1]  # Latest negative lag (closest to 0)
        elif len(positive_peaks) > 0:
            first_peak = positive_peaks[0]
        else:
            first_peak = negative_peaks[-1]

        delay = lags[first_peak] / sample_rate

        # Calculate confidence based on how many other peaks there are
        num_peaks = len(peaks)
        confidence = 1.0 / (1.0 + 0.2 * (num_peaks - 1))  # Decreases with more peaks

        metadata = {
            "strategy": "first_peak",
            "peak_value": correlation[first_peak],
            "num_peaks": num_peaks,
            "threshold": threshold,
            "confidence": confidence,
            "all_peaks": peaks.tolist()[:5],  # First 5 peaks for debugging
        }

        return first_peak, delay, metadata


class MultiPeakStrategy(CorrelationStrategy):
    """
    Detect and analyze multiple peaks (direct path + echoes).

    Returns information about all significant peaks for:
    - Room acoustics analysis
    - Echo visualization
    - Quality assessment
    """

    def __init__(self, threshold_ratio=0.2, max_peaks=5):
        self.threshold_ratio = threshold_ratio
        self.max_peaks = max_peaks

    def find_peak(
        self, correlation: np.ndarray, lags: np.ndarray, sample_rate: float
    ) -> Tuple[int, float, Dict]:

        max_corr = np.max(np.abs(correlation))
        threshold = max_corr * self.threshold_ratio

        # Find all significant peaks
        peaks, properties = find_peaks(
            np.abs(correlation),
            height=threshold,
            distance=int(0.005 * sample_rate),  # Min 5ms between peaks
        )

        # Sort by strength
        peak_strengths = np.abs(correlation[peaks])
        sorted_indices = np.argsort(peak_strengths)[::-1]
        top_peaks = peaks[sorted_indices[: self.max_peaks]]

        # Primary peak is strongest
        primary_idx = top_peaks[0]
        primary_delay = lags[primary_idx] / sample_rate

        # Analyze all peaks
        peak_info = []
        for idx in top_peaks:
            peak_info.append(
                {
                    "lag_samples": int(lags[idx]),
                    "delay_ms": lags[idx] / sample_rate * 1000,
                    "distance_m": abs(lags[idx] / sample_rate * 343),
                    "correlation_value": float(correlation[idx]),
                    "relative_strength": float(np.abs(correlation[idx]) / max_corr),
                }
            )

        # Assess environment
        if len(top_peaks) == 1:
            environment = "clean"  # Single path, no significant echoes
            confidence = 1.0
        elif len(top_peaks) <= 3:
            environment = "moderate_echoes"  # Some reflections
            confidence = 0.8
        else:
            environment = "highly_reverberant"  # Many reflections
            confidence = 0.6

        metadata = {
            "strategy": "multi_peak",
            "peak_value": correlation[primary_idx],
            "num_peaks": len(top_peaks),
            "environment": environment,
            "confidence": confidence,
            "peaks": peak_info,
            "echo_delays_ms": [p["delay_ms"] for p in peak_info[1:]],  # Exclude primary
        }

        return primary_idx, primary_delay, metadata


class WindowedSearchStrategy(CorrelationStrategy):
    """
    Search for peak only within expected time window.

    Useful when:
    - Approximate distance is known
    - Want to reject distant echoes
    - Multiple rooms/spaces might create ambiguity
    """

    def __init__(self, min_distance_m=0, max_distance_m=100):
        """
        Args:
            min_distance_m: Minimum expected distance
            max_distance_m: Maximum expected distance
        """
        self.min_distance_m = min_distance_m
        self.max_distance_m = max_distance_m
        self.speed_of_sound = 343.0  # m/s

    def find_peak(
        self, correlation: np.ndarray, lags: np.ndarray, sample_rate: float
    ) -> Tuple[int, float, Dict]:

        # Convert distance to time
        min_delay_s = self.min_distance_m / self.speed_of_sound
        max_delay_s = self.max_distance_m / self.speed_of_sound

        # Convert to samples
        center_idx = len(correlation) // 2
        min_lag_samples = int(min_delay_s * sample_rate)
        max_lag_samples = int(max_delay_s * sample_rate)

        # Create search window
        search_start = max(0, center_idx + min_lag_samples)
        search_end = min(len(correlation), center_idx + max_lag_samples)

        # Also search negative lags (in case reference/remote are swapped)
        search_start_neg = max(0, center_idx - max_lag_samples)
        search_end_neg = min(len(correlation), center_idx - min_lag_samples)

        # Find strongest peak in windows
        positive_window = np.abs(correlation[search_start:search_end])
        negative_window = np.abs(correlation[search_start_neg:search_end_neg])

        if len(positive_window) > 0:
            pos_max = np.max(positive_window)
            pos_idx = np.argmax(positive_window) + search_start
        else:
            pos_max = 0
            pos_idx = 0

        if len(negative_window) > 0:
            neg_max = np.max(negative_window)
            neg_idx = np.argmax(negative_window) + search_start_neg
        else:
            neg_max = 0
            neg_idx = 0

        # Choose stronger
        if pos_max > neg_max:
            peak_idx = pos_idx
        else:
            peak_idx = neg_idx

        delay = lags[peak_idx] / sample_rate
        distance = abs(delay * self.speed_of_sound)

        # Check if within expected range
        in_range = self.min_distance_m <= distance <= self.max_distance_m
        confidence = 1.0 if in_range else 0.5

        metadata = {
            "strategy": "windowed_search",
            "peak_value": correlation[peak_idx],
            "distance_m": distance,
            "in_range": in_range,
            "confidence": confidence,
            "search_window": f"{self.min_distance_m}-{self.max_distance_m}m",
        }

        return peak_idx, delay, metadata


# Factory function to choose strategy based on environment
def get_correlation_strategy(environment="auto", **kwargs) -> CorrelationStrategy:
    """
    Get appropriate correlation strategy for environment.

    Args:
        environment:
            'auto' - Use strongest peak (current default)
            'outdoor' - Use strongest peak (minimal echoes)
            'indoor_open' - Use first peak (some echoes)
            'reverberant' - Use first peak (many echoes)
            'multi_path' - Use multi-peak analysis
            'windowed' - Use windowed search with known distance range
        **kwargs: Strategy-specific parameters

    Returns:
        CorrelationStrategy instance
    """
    strategies = {
        "auto": StrongestPeakStrategy,
        "outdoor": StrongestPeakStrategy,
        "indoor_open": lambda: FirstPeakStrategy(threshold_ratio=0.3),
        "reverberant": lambda: FirstPeakStrategy(threshold_ratio=0.2),
        "multi_path": lambda: MultiPeakStrategy(threshold_ratio=0.2, max_peaks=5),
        "windowed": lambda: WindowedSearchStrategy(**kwargs),
    }

    if environment not in strategies:
        logger.warning(f"Unknown environment '{environment}', using 'auto'")
        environment = "auto"

    strategy_class = strategies[environment]

    if callable(strategy_class):
        if environment == "windowed" and not kwargs:
            logger.error(
                "WindowedSearchStrategy requires min_distance_m and max_distance_m"
            )
            return StrongestPeakStrategy()
        return strategy_class()
    else:
        return strategy_class(**kwargs)


if __name__ == "__main__":
    # Demo/test different strategies
    import matplotlib.pyplot as plt

    # Create synthetic correlation with echoes
    sample_rate = 44100
    t = np.linspace(-0.1, 0.1, 8820)  # ±100ms

    # Direct path at 30ms
    direct = np.exp(-((t - 0.030) ** 2) / 0.0001) * 1000

    # Echo 1 at 45ms (weaker)
    echo1 = np.exp(-((t - 0.045) ** 2) / 0.0001) * 600

    # Echo 2 at 60ms (even weaker)
    echo2 = np.exp(-((t - 0.060) ** 2) / 0.0001) * 300

    # Combined with noise
    correlation = direct + echo1 + echo2 + np.random.randn(len(t)) * 50
    lags = (t * sample_rate).astype(int)

    # Test each strategy
    strategies = {
        "Strongest Peak": StrongestPeakStrategy(),
        "First Peak": FirstPeakStrategy(threshold_ratio=0.2),
        "Multi-Peak": MultiPeakStrategy(threshold_ratio=0.2, max_peaks=5),
    }

    fig, axes = plt.subplots(len(strategies), 1, figsize=(12, 10))

    for ax, (name, strategy) in zip(axes, strategies.items()):
        peak_idx, delay, metadata = strategy.find_peak(correlation, lags, sample_rate)

        ax.plot(t * 1000, correlation, linewidth=1, alpha=0.7, label="Correlation")
        ax.axvline(
            delay * 1000,
            color="red",
            linestyle="--",
            label=f"Detected: {delay*1000:.1f}ms",
        )
        ax.axvline(30, color="green", linestyle=":", alpha=0.5, label="True: 30ms")

        ax.set_title(
            f"{name} - Delay: {delay*1000:.1f}ms, Confidence: {metadata['confidence']:.2f}"
        )
        ax.set_xlabel("Time Lag (ms)")
        ax.set_ylabel("Correlation")
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("/tmp/correlation_strategies_demo.png", dpi=150)
    print("Demo saved to /tmp/correlation_strategies_demo.png")
