"""Continuous NTP synchronization with drift compensation.

This module provides robust time synchronization for distributed audio systems
where precise timing is critical for cross-correlation.
"""

import logging
import ntplib
import threading
import time
from collections import deque
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class TimeSync:
    """Continuous NTP synchronization with clock drift tracking and compensation.

    Features:
    - Periodic NTP synchronization (default: every 5 minutes)
    - Clock drift estimation using linear regression
    - Multi-server redundancy for reliability
    - Graceful degradation when NTP unavailable
    - Thread-safe offset retrieval

    Usage:
        time_sync = TimeSync(ntp_server="pool.ntp.org", sync_interval=300)
        time_sync.start()

        # Get current offset with drift compensation
        offset = time_sync.get_offset()
        corrected_time = time.time() + offset
    """

    def __init__(
        self,
        ntp_server: str = "pool.ntp.org",
        sync_interval: int = 300,
        max_history: int = 20,
    ):
        """Initialize time synchronization.

        Args:
            ntp_server: Primary NTP server hostname
            sync_interval: Seconds between sync attempts (default: 300 = 5 minutes)
            max_history: Number of sync measurements to keep for drift calculation
        """
        self.ntp_server = ntp_server
        self.sync_interval = sync_interval
        self.max_history = max_history

        # NTP server list (fallbacks)
        self.ntp_servers = [
            ntp_server,
            "time.google.com",
            "time.cloudflare.com",
            "time.nist.gov",
            "pool.ntp.org",
        ]

        # Synchronization state
        self.offset_history = deque(maxlen=max_history)
        self.drift_ppm = 0.0  # Clock drift in parts per million
        self.last_sync_time = None
        self.last_offset = 0.0
        self.sync_success_count = 0
        self.sync_failure_count = 0

        # Thread control
        self.lock = threading.Lock()
        self.running = False
        self.sync_thread = None

    def start(self):
        """Start continuous synchronization in background thread."""
        if self.running:
            logger.warning("TimeSync already running")
            return

        self.running = True

        # Perform initial sync synchronously
        logger.info("Performing initial NTP synchronization...")
        self._sync_once()

        # Start background sync thread
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()
        logger.info(
            f"TimeSync started: sync_interval={self.sync_interval}s, "
            f"initial_offset={self.last_offset:.3f}s"
        )

    def stop(self):
        """Stop synchronization thread."""
        if not self.running:
            return

        logger.info("Stopping TimeSync...")
        self.running = False

        if self.sync_thread and self.sync_thread.is_alive():
            self.sync_thread.join(timeout=5)

        logger.info(
            f"TimeSync stopped: successes={self.sync_success_count}, "
            f"failures={self.sync_failure_count}"
        )

    def get_offset(self) -> float:
        """Get current estimated time offset with drift compensation.

        Returns:
            Time offset in seconds (add to time.time() to get corrected time)
        """
        with self.lock:
            if self.last_sync_time is None:
                logger.warning("No NTP sync yet, returning 0 offset")
                return 0.0

            # Calculate time since last sync
            elapsed = time.time() - self.last_sync_time

            # Apply drift compensation
            drift_correction = (self.drift_ppm / 1e6) * elapsed

            return self.last_offset + drift_correction

    def get_stats(self) -> dict:
        """Get synchronization statistics.

        Returns:
            Dictionary with sync statistics
        """
        with self.lock:
            return {
                "last_offset_seconds": self.last_offset,
                "drift_ppm": self.drift_ppm,
                "seconds_since_sync": (
                    time.time() - self.last_sync_time if self.last_sync_time else None
                ),
                "success_count": self.sync_success_count,
                "failure_count": self.sync_failure_count,
                "history_size": len(self.offset_history),
            }

    def _sync_loop(self):
        """Background synchronization loop."""
        while self.running:
            time.sleep(self.sync_interval)
            if self.running:  # Check again after sleep
                self._sync_once()

    def _sync_once(self):
        """Perform single NTP synchronization with multi-server fallback."""
        offset = None
        last_error = None

        # Try each server until one succeeds
        for server in self.ntp_servers:
            try:
                client = ntplib.NTPClient()
                response = client.request(server, version=3, timeout=5)
                offset = response.offset

                logger.debug(
                    f"NTP sync successful: server={server}, offset={offset:.3f}s, "
                    f"stratum={response.stratum}, precision={response.precision}"
                )
                break

            except ntplib.NTPException as e:
                logger.debug(f"NTP error for {server}: {e}")
                last_error = e
            except Exception as e:
                logger.debug(f"NTP failed for {server}: {e}")
                last_error = e

        if offset is None:
            # All servers failed
            self.sync_failure_count += 1
            logger.error(
                f"All NTP servers failed! Last error: {last_error}. "
                f"Failures: {self.sync_failure_count}"
            )
            return

        # Success! Update state
        with self.lock:
            current_time = time.time()

            # Add to history
            self.offset_history.append((current_time, offset))

            # Calculate drift if we have enough history
            if len(self.offset_history) >= 2:
                self._calculate_drift()

            # Update current offset
            self.last_offset = offset
            self.last_sync_time = current_time
            self.sync_success_count += 1

            logger.info(
                f"Time sync: offset={offset*1000:.1f}ms, drift={self.drift_ppm:.2f}ppm, "
                f"successes={self.sync_success_count}, failures={self.sync_failure_count}"
            )

    def _calculate_drift(self):
        """Calculate clock drift using linear regression on offset history.

        Clock drift is estimated by fitting a line to offset measurements over time.
        The slope of this line gives the drift rate.
        """
        if len(self.offset_history) < 2:
            return

        # Extract times and offsets
        times = np.array([t for t, _ in self.offset_history])
        offsets = np.array([o for _, o in self.offset_history])

        # Normalize times to prevent numerical issues
        times = times - times[0]

        try:
            # Linear regression: offset = drift_rate * time + base_offset
            # We only care about the slope (drift_rate)
            coeffs = np.polyfit(times, offsets, deg=1)
            drift_per_second = coeffs[0]

            # Convert to parts per million (ppm)
            self.drift_ppm = drift_per_second * 1e6

            logger.debug(
                f"Drift calculation: {self.drift_ppm:.2f}ppm "
                f"({len(self.offset_history)} samples over {times[-1]:.0f}s)"
            )

        except Exception as e:
            logger.warning(f"Failed to calculate drift: {e}")


# Convenience function for simple usage
def create_time_sync(
    ntp_server: str = "pool.ntp.org", sync_interval: int = 300
) -> TimeSync:
    """Create and start a TimeSync instance.

    Args:
        ntp_server: Primary NTP server
        sync_interval: Seconds between syncs

    Returns:
        Started TimeSync instance
    """
    ts = TimeSync(ntp_server=ntp_server, sync_interval=sync_interval)
    ts.start()
    return ts


if __name__ == "__main__":
    # Example usage and testing
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("Testing TimeSync...")
    ts = TimeSync(sync_interval=10)  # 10 seconds for testing
    ts.start()

    try:
        for i in range(30):
            time.sleep(1)
            offset = ts.get_offset()
            stats = ts.get_stats()
            print(
                f"[{i+1:2d}s] Offset: {offset*1000:+7.2f}ms, "
                f"Drift: {stats['drift_ppm']:+6.2f}ppm, "
                f"Success: {stats['success_count']}, "
                f"Fail: {stats['failure_count']}"
            )
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        ts.stop()
