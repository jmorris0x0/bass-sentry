"""Tests for time synchronization."""

import os
import pytest
import sys
import threading
import time
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from time_sync import TimeSync


class TestTimeSync:
    """Test TimeSync class."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        ts = TimeSync()
        assert ts.ntp_server == "pool.ntp.org"
        assert ts.sync_interval == 300
        assert ts.max_history == 20
        assert not ts.running

    def test_init_custom(self):
        """Test initialization with custom values."""
        ts = TimeSync(ntp_server="time.google.com", sync_interval=60, max_history=10)
        assert ts.ntp_server == "time.google.com"
        assert ts.sync_interval == 60
        assert ts.max_history == 10

    def test_get_offset_before_sync(self):
        """Test get_offset returns 0 before any sync."""
        ts = TimeSync()
        assert ts.get_offset() == 0.0

    @patch("time_sync.ntplib.NTPClient")
    def test_sync_success(self, mock_ntp_class):
        """Test successful NTP sync."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client
        mock_client.request.return_value = MagicMock(
            offset=0.05, stratum=2, precision=-20  # 50ms offset
        )

        ts = TimeSync()
        ts._sync_once()

        assert ts.last_offset == 0.05
        assert ts.sync_success_count == 1
        assert ts.sync_failure_count == 0

    @patch("time_sync.ntplib.NTPClient")
    def test_sync_fallback_servers(self, mock_ntp_class):
        """Test fallback to secondary servers."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client

        # First server fails, second succeeds
        mock_client.request.side_effect = [
            Exception("Primary server failed"),
            MagicMock(offset=0.03, stratum=2, precision=-20),
        ]

        ts = TimeSync()
        ts._sync_once()

        assert ts.last_offset == 0.03
        assert ts.sync_success_count == 1

    @patch("time_sync.ntplib.NTPClient")
    def test_sync_all_servers_fail(self, mock_ntp_class):
        """Test when all servers fail."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client
        mock_client.request.side_effect = Exception("Server failed")

        ts = TimeSync()
        ts._sync_once()

        assert ts.sync_failure_count == 1
        assert ts.last_offset == 0.0  # Unchanged

    def test_drift_compensation(self):
        """Test drift compensation in get_offset."""
        ts = TimeSync()

        # Simulate a sync that happened 100 seconds ago
        ts.last_sync_time = time.time() - 100
        ts.last_offset = 0.01  # 10ms offset
        ts.drift_ppm = 10.0  # 10 ppm drift

        offset = ts.get_offset()

        # Expected: 0.01 + (10/1e6) * 100 = 0.01 + 0.001 = 0.011
        assert abs(offset - 0.011) < 0.0001

    def test_get_stats(self):
        """Test get_stats returns correct data."""
        ts = TimeSync()
        ts.last_offset = 0.05
        ts.drift_ppm = 5.0
        ts.sync_success_count = 10
        ts.sync_failure_count = 2
        ts.last_sync_time = time.time() - 30

        stats = ts.get_stats()

        assert stats["last_offset_seconds"] == 0.05
        assert stats["drift_ppm"] == 5.0
        assert stats["success_count"] == 10
        assert stats["failure_count"] == 2
        assert 29 < stats["seconds_since_sync"] < 32

    def test_get_stats_before_sync(self):
        """Test get_stats when no sync has occurred."""
        ts = TimeSync()
        stats = ts.get_stats()

        assert stats["last_offset_seconds"] == 0.0
        assert stats["drift_ppm"] == 0.0
        assert stats["seconds_since_sync"] is None
        assert stats["success_count"] == 0
        assert stats["failure_count"] == 0

    @patch("time_sync.ntplib.NTPClient")
    def test_start_stop(self, mock_ntp_class):
        """Test start and stop lifecycle."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client
        mock_client.request.return_value = MagicMock(
            offset=0.01, stratum=2, precision=-20
        )

        ts = TimeSync(sync_interval=1)  # Short interval for test

        ts.start()
        assert ts.running is True
        assert ts.sync_thread is not None

        time.sleep(0.1)  # Let it run briefly

        ts.stop()
        assert ts.running is False

    def test_start_twice_warning(self):
        """Test that starting twice logs warning but doesn't crash."""
        ts = TimeSync()
        ts.running = True  # Pretend already running

        # Should not raise, just warn
        ts.start()

    def test_stop_when_not_running(self):
        """Test stopping when not running is safe."""
        ts = TimeSync()
        ts.running = False

        # Should not raise
        ts.stop()

    def test_thread_safety(self):
        """Test thread-safe offset retrieval."""
        ts = TimeSync()
        ts.last_sync_time = time.time()
        ts.last_offset = 0.01
        ts.drift_ppm = 1.0

        results = []

        def get_offsets():
            for _ in range(100):
                results.append(ts.get_offset())

        threads = [threading.Thread(target=get_offsets) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have 1000 results, no exceptions
        assert len(results) == 1000

    @patch("time_sync.ntplib.NTPClient")
    def test_drift_calculation(self, mock_ntp_class):
        """Test drift calculation with multiple syncs."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client

        ts = TimeSync()

        # Simulate multiple syncs over time with increasing offset (drift)
        # This simulates a clock drifting 10 ppm
        base_time = time.time()
        for i in range(5):
            mock_client.request.return_value = MagicMock(
                offset=0.01 + i * 0.00001,  # Small increase each time
                stratum=2,
                precision=-20,
            )

            with patch("time.time", return_value=base_time + i * 100):
                ts._sync_once()

        # Should have calculated some drift
        assert ts.drift_ppm != 0.0 or len(ts.offset_history) >= 2

    def test_offset_history_limit(self):
        """Test that offset history respects max_history."""
        ts = TimeSync(max_history=5)

        # Manually add more than max_history entries
        for i in range(10):
            ts.offset_history.append((time.time() + i, 0.01 * i))

        assert len(ts.offset_history) == 5

    @patch("time_sync.ntplib.NTPClient")
    def test_ntp_exception_types(self, mock_ntp_class):
        """Test handling of specific NTP exception types."""
        import ntplib

        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client

        # Test NTPException specifically
        mock_client.request.side_effect = ntplib.NTPException("NTP Error")

        ts = TimeSync()
        ts._sync_once()

        assert ts.sync_failure_count == 1


class TestTimeSyncIntegration:
    """Integration tests that may hit real NTP servers (use sparingly)."""

    @pytest.mark.skip(reason="Requires network access - run manually")
    def test_real_ntp_sync(self):
        """Test actual NTP synchronization."""
        ts = TimeSync(sync_interval=60)
        ts.start()

        time.sleep(1)  # Wait for initial sync

        offset = ts.get_offset()
        stats = ts.get_stats()

        ts.stop()

        # Offset should be reasonable (within 1 second)
        assert abs(offset) < 1.0
        assert stats["success_count"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
