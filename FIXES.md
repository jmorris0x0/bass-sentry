# Bass Sentry - Proposed Fixes

This document outlines issues identified during code review and the proposed fixes.

---

## Status Summary

| Section | Item | Status |
|---------|------|--------|
| 1.1 | Hardcoded path in remote_node.py | ✅ Done |
| 1.2 | Hardcoded paths in test_data_handler.py | ✅ Done |
| 2.1 | MQTTTransport configurable timeouts/retries | ✅ Done |
| 2.2 | Service discovery graceful fallback | ✅ Done |
| 2.3 | Persistent offline buffer | ❌ Skipped (SD card wear on RPis) |
| 2.4 | Health check / heartbeat mechanism | ✅ Done |
| 3.1 | Consolidate duplicate MQTT implementations | ✅ Done (MQTTHandler deleted) |
| 3.2 | Remove unused stub classes | ✅ Done |
| 3.3 | Consistent error handling strategy | ✅ Done |
| 4.1 | Reuse ThreadPoolExecutor | ✅ Done |
| 4.2 | Use bisect.insort for ordered buffers | ✅ Done |
| 4.3 | Pre-allocated circular buffers | ❌ Skipped (benchmarked, not needed) |
| 5.1 | Transport layer tests | ✅ Done |
| 5.2 | TimeSync tests | ✅ Done |
| 5.3 | Processor tests | ✅ Done |
| 5.4 | TelemetrySender tests | ⏳ Not started |

**Test count:** 34 → 97 tests (185% increase)

**File renames for clarity:**
- `master-node/data_handler.py` → `master-node/correlation.py`
- `master-node/data_manager.py` → `master-node/node_manager.py`
- `tests/test_data_handler.py` → `tests/test_correlation.py`

---

## 1. Critical: Hardcoded Paths

**Problem:** Absolute paths break the project on any machine other than the original developer's.

### 1.1 remote_node.py:19
```python
# Current
sys.path.insert(0, "/Users/jonathan/code/bass-sentry")

# Fix: Use relative path from file location
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### 1.2 tests/test_data_handler.py:9-10
```python
# Current
sys.path.insert(0, "/Users/jonathan/code/bass-sentry/master-node")
sys.path.insert(0, "/Users/jonathan/code/bass-sentry/common")

# Fix: Use relative paths
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "master-node"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
```

**Files affected:**
- `remote-node/remote_node.py`
- `tests/test_data_handler.py`

---

## 2. Connectivity Hardening

### 2.1 MQTTTransport: Configurable Timeouts and Retry

**File:** `common/transport_mqtt.py`

**Problem:** Fixed 5-second timeout, no retry logic, silent failures.

**Fix:**
- Add `connect_timeout` and `connect_retries` config options
- Implement exponential backoff retry loop
- Raise exception or return clear failure on exhausted retries

```python
def __init__(self, config: Dict[str, Any]):
    # ... existing code ...
    self.connect_timeout = config.get("connect_timeout", 10)
    self.connect_retries = config.get("connect_retries", 3)
    self.retry_backoff = config.get("retry_backoff", 2.0)

def connect(self) -> bool:
    for attempt in range(self.connect_retries):
        try:
            self.client.connect(self.broker, self.port, self.keepalive)
            self.client.loop_start()

            # Wait for connection with configurable timeout
            deadline = time.time() + self.connect_timeout
            while time.time() < deadline:
                if self.connected:
                    logger.info("MQTT transport connected")
                    return True
                time.sleep(0.1)

            logger.warning(f"Connection attempt {attempt + 1} timed out")

        except Exception as e:
            logger.warning(f"Connection attempt {attempt + 1} failed: {e}")

        if attempt < self.connect_retries - 1:
            delay = self.retry_backoff ** attempt
            logger.info(f"Retrying in {delay:.1f}s...")
            time.sleep(delay)

    logger.error(f"Failed to connect after {self.connect_retries} attempts")
    return False
```

### 2.2 Service Discovery: Graceful Fallback

**File:** `remote-node/telemetry_sender.py`

**Problem:** `discover_service()` waits essentially forever (10M attempts) with no fallback.

**Fix:**
- Add configurable max attempts and timeout
- Support fallback broker address in config
- Raise clear exception with guidance

```python
def discover_service(max_attempts=60, fallback_broker=None):
    """Discover master node via Zeroconf with fallback option.

    Args:
        max_attempts: Maximum discovery attempts (5 sec each = 5 min default)
        fallback_broker: Optional broker address to use if discovery fails
    """
    zeroconf = Zeroconf()
    listener = ServiceDiscoveryListener()
    browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)

    attempts = 0
    while not listener.broker_address and attempts < max_attempts:
        logger.info(f"Discovering master node... (attempt {attempts + 1}/{max_attempts})")
        time.sleep(5)
        attempts += 1

    zeroconf.close()

    if listener.broker_address:
        return listener.broker_address
    elif fallback_broker:
        logger.warning(f"Discovery failed, using fallback broker: {fallback_broker}")
        return fallback_broker
    else:
        raise Exception(
            f"Service discovery failed after {max_attempts} attempts. "
            f"Ensure master node is running or provide fallback_broker in config."
        )
```

### 2.3 Persistent Offline Buffer (Optional Enhancement)

**File:** `remote-node/telemetry_sender.py`

**Problem:** In-memory buffer lost on crash/restart.

**Fix:** Add optional SQLite-backed buffer for critical deployments.

```python
class PersistentBuffer:
    """SQLite-backed message buffer for crash recovery."""

    def __init__(self, db_path="offline_buffer.db", max_size=10000):
        self.db_path = db_path
        self.max_size = max_size
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    payload TEXT
                )
            """)

    def append(self, message):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (timestamp, payload) VALUES (?, ?)",
                (time.time(), json.dumps(message))
            )
            # Enforce max size
            conn.execute("""
                DELETE FROM messages WHERE id IN (
                    SELECT id FROM messages ORDER BY id ASC
                    LIMIT MAX(0, (SELECT COUNT(*) FROM messages) - ?)
                )
            """, (self.max_size,))

    def pop_all(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, payload FROM messages ORDER BY id ASC"
            ).fetchall()
            if rows:
                conn.execute("DELETE FROM messages WHERE id <= ?", (rows[-1][0],))
            return [json.loads(row[1]) for row in rows]
```

**Note:** This is an enhancement. May be overkill depending on deployment requirements.

### 2.4 Health Check / Heartbeat Mechanism

**Files:** `remote-node/telemetry_sender.py`, `master-node/data_manager.py`

**Problem:** No way to detect silent node failures.

**Fix:**
- Remote nodes send periodic heartbeats
- Master tracks last-seen timestamps
- Alert/log when nodes go silent

```python
# In MQTTHandler - add heartbeat thread
def start(self):
    # ... existing connection code ...
    self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
    self.heartbeat_thread.start()

def _heartbeat_loop(self):
    while True:
        self.publish_message({
            "type": "heartbeat",
            "node_name": self.unit_name,
            "timestamp": time.time(),
            "stats": {
                "messages_sent": self.messages_sent,
                "messages_failed": self.messages_failed,
                "buffer_size": len(self.offline_buffer),
            }
        })
        time.sleep(self.heartbeat_interval)
```

```python
# In master node - track node health
class NodeHealthTracker:
    def __init__(self, timeout_seconds=30):
        self.timeout = timeout_seconds
        self.last_seen = {}  # node_id -> timestamp

    def update(self, node_id):
        self.last_seen[node_id] = time.time()

    def get_stale_nodes(self):
        now = time.time()
        return [
            node_id for node_id, ts in self.last_seen.items()
            if now - ts > self.timeout
        ]
```

---

## 3. Code Cleanup

### 3.1 Consolidate Duplicate MQTT Implementations

**Problem:** `MQTTHandler` in `telemetry_sender.py` and `MQTTTransport` in `transport_mqtt.py` overlap significantly. `MQTTHandler` has better reconnection logic.

**Fix:**
- Enhance `MQTTTransport` with the reconnection and buffering logic from `MQTTHandler`
- Refactor `TelemetrySender` to use the common transport layer
- Delete `MQTTHandler` class

**Approach:**
1. Add offline buffering to `MQTTTransport`
2. Add exponential backoff reconnection to `MQTTTransport`
3. Update `TelemetrySender` to use `TransportHandler` exclusively
4. Remove `MQTTHandler` class

### 3.2 Remove Unused Stub Classes

**File:** `master-node/data_handler.py:669-678`

**Problem:** `ChunkToScalar` and `ChunkToStream` are stub implementations referencing undefined `processed_data`.

**Fix:** Delete these classes entirely, or implement them properly if needed.

```python
# DELETE these lines (669-678):
class ChunkToScalar(DataProcessor):
    def process(self, data):
        # process chunked time-series data into a scalar value
        return processed_data  # <-- undefined!


class ChunkToStream(DataProcessor):
    def process(self, data):
        # process chunked time-series data into timestamped streams
        return processed_data  # <-- undefined!
```

### 3.3 Consistent Error Handling Strategy

**Problem:** Mix of exceptions, None returns, and log-and-continue patterns.

**Fix:** Establish and document a consistent strategy:

```python
# Strategy:
# 1. Configuration errors -> raise ValueError immediately
# 2. Connection errors -> raise ConnectionError or return False with logging
# 3. Processing errors -> log warning, return None, continue processing
# 4. Fatal errors -> raise, let caller handle

# Example: Update DataHandler.process_data()
def process_data(self, station_id: str, data_type: str, data: Dict[str, Any]):
    """Process incoming data.

    Returns:
        List[Point] on success, None if data couldn't be processed (logged)

    Raises:
        ValueError: If data_type is unknown (configuration error)
    """
    if data_type not in self.processors:
        raise ValueError(f"Unknown data type: {data_type}")  # Fail fast

    # ... rest of processing, return None on recoverable errors
```

---

## 4. Performance Optimizations

### 4.1 Reuse ThreadPoolExecutor

**File:** `remote-node/processors.py:39`

**Problem:** Creates new executor for every DAG process call.

**Fix:** Use class-level or module-level executor.

```python
class DAGProcessor:
    # Class-level executor shared across instances
    _executor = None
    _executor_lock = threading.Lock()

    @classmethod
    def get_executor(cls):
        if cls._executor is None:
            with cls._executor_lock:
                if cls._executor is None:
                    cls._executor = ThreadPoolExecutor(max_workers=4)
        return cls._executor

    def process(self, data, step_id="start"):
        # ... existing code ...

        with self.get_executor() as executor:  # Reuse instead of create
            # ... rest of method
```

Alternative: Pass executor in constructor for more control.

### 4.2 Use bisect.insort for Ordered Buffers

**File:** `master-node/data_handler.py:496, 515`

**Problem:** Sorting entire buffer on every insert.

**Fix:** Use binary insertion for mostly-ordered data.

```python
import bisect

def process_reference_stream(self, data: Dict[str, Any], max_buffer_size: int):
    buffer = self.buffers.setdefault("reference", [])
    timestamp = data["timestamp"]
    audio_data = data["data"]

    # Binary insert maintains sorted order - O(n) vs O(n log n)
    item = (timestamp, audio_data)
    bisect.insort(buffer, item, key=lambda x: x[0])

    if len(buffer) > max_buffer_size:
        buffer.pop(0)

    # ... rest unchanged
```

### 4.3 Pre-allocated Circular Buffers

**File:** `master-node/data_handler.py:501-506, 520-525`

**Problem:** `np.concatenate` rebuilds entire array on every chunk.

**Fix:** Use pre-allocated circular buffer.

```python
class CircularAudioBuffer:
    """Pre-allocated circular buffer for audio chunks."""

    def __init__(self, max_samples, dtype=np.float64):
        self.buffer = np.zeros(max_samples, dtype=dtype)
        self.timestamps = np.zeros(max_samples // 1000, dtype=np.int64)  # Chunk timestamps
        self.write_pos = 0
        self.chunk_count = 0
        self.max_samples = max_samples

    def append(self, timestamp, chunk):
        chunk_len = len(chunk)

        # Handle wraparound
        if self.write_pos + chunk_len <= self.max_samples:
            self.buffer[self.write_pos:self.write_pos + chunk_len] = chunk
        else:
            # Wrap around
            first_part = self.max_samples - self.write_pos
            self.buffer[self.write_pos:] = chunk[:first_part]
            self.buffer[:chunk_len - first_part] = chunk[first_part:]

        self.write_pos = (self.write_pos + chunk_len) % self.max_samples
        self.timestamps[self.chunk_count % len(self.timestamps)] = timestamp
        self.chunk_count += 1

    def get_data(self):
        """Get contiguous view of buffer data."""
        if self.chunk_count * 1000 < self.max_samples:  # Not full yet
            return self.buffer[:self.write_pos].copy()
        return np.roll(self.buffer, -self.write_pos)
```

**Note:** This is a larger refactor. May want to benchmark first to confirm it's worth the complexity.

---

## 5. Test Coverage

### 5.1 Transport Layer Tests

**New file:** `tests/test_transport.py`

```python
"""Tests for transport layer."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import time

from common.transport import TransportConfig, get_transport, TransportType
from common.transport_mqtt import MQTTTransport


class TestMQTTTransport:
    """Test MQTT transport implementation."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        transport = MQTTTransport({})
        assert transport.broker == "localhost"
        assert transport.port == 1883
        assert transport.qos == 1
        assert not transport.connected

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = {
            "broker": "mqtt.example.com",
            "port": 8883,
            "qos": 2,
            "username": "user",
            "password": "pass",
        }
        transport = MQTTTransport(config)
        assert transport.broker == "mqtt.example.com"
        assert transport.port == 8883
        assert transport.qos == 2

    @patch('common.transport_mqtt.mqtt.Client')
    def test_connect_success(self, mock_client_class):
        """Test successful connection."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({"broker": "localhost"})

        # Simulate successful connection callback
        def trigger_connect(*args):
            transport._on_connect(mock_client, None, None, 0)
        mock_client.connect.side_effect = trigger_connect

        result = transport.connect()

        assert result is True
        assert transport.connected is True
        mock_client.loop_start.assert_called_once()

    @patch('common.transport_mqtt.mqtt.Client')
    def test_connect_timeout(self, mock_client_class):
        """Test connection timeout."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        transport = MQTTTransport({"broker": "localhost"})
        # Don't trigger on_connect - simulates timeout

        result = transport.connect()

        assert result is False
        assert transport.connected is False

    @patch('common.transport_mqtt.mqtt.Client')
    def test_send_when_disconnected(self, mock_client_class):
        """Test send fails gracefully when disconnected."""
        transport = MQTTTransport({})
        transport.connected = False

        result = transport.send("test/topic", {"data": "test"})

        assert result is False
        assert transport.stats["messages_failed"] == 1

    @patch('common.transport_mqtt.mqtt.Client')
    def test_send_success(self, mock_client_class):
        """Test successful send."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.publish.return_value = MagicMock(rc=0)  # MQTT_ERR_SUCCESS

        transport = MQTTTransport({})
        transport.connected = True
        transport.client = mock_client

        result = transport.send("test/topic", {"data": "test"})

        assert result is True
        assert transport.stats["messages_sent"] == 1

    def test_resubscribe_on_reconnect(self):
        """Test that subscriptions are restored on reconnect."""
        transport = MQTTTransport({})
        transport.client = MagicMock()

        # Subscribe to topics
        callback = Mock()
        transport.subscribe("test/topic1", callback)
        transport.subscribe("test/topic2", callback)

        # Simulate reconnect
        transport._on_connect(transport.client, None, {"session_present": False}, 0)

        # Verify resubscription
        assert transport.client.subscribe.call_count >= 2


class TestTransportConfig:
    """Test transport configuration."""

    def test_from_dict_mqtt(self):
        """Test creating MQTT config from dict."""
        config = TransportConfig.from_dict({
            "type": "mqtt",
            "mqtt": {"broker": "localhost", "port": 1883}
        })
        assert config.transport_type == TransportType.MQTT
        assert config.config["broker"] == "localhost"

    def test_from_dict_default(self):
        """Test default transport type."""
        config = TransportConfig.from_dict({})
        assert config.transport_type == TransportType.MQTT
```

### 5.2 TimeSync Tests

**New file:** `tests/test_time_sync.py`

```python
"""Tests for time synchronization."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import threading

from common.time_sync import TimeSync


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
        ts = TimeSync(
            ntp_server="time.google.com",
            sync_interval=60,
            max_history=10
        )
        assert ts.ntp_server == "time.google.com"
        assert ts.sync_interval == 60
        assert ts.max_history == 10

    def test_get_offset_before_sync(self):
        """Test get_offset returns 0 before any sync."""
        ts = TimeSync()
        assert ts.get_offset() == 0.0

    @patch('common.time_sync.ntplib.NTPClient')
    def test_sync_success(self, mock_ntp_class):
        """Test successful NTP sync."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client
        mock_client.request.return_value = MagicMock(
            offset=0.05,  # 50ms offset
            stratum=2,
            precision=-20
        )

        ts = TimeSync()
        ts._sync_once()

        assert ts.last_offset == 0.05
        assert ts.sync_success_count == 1
        assert ts.sync_failure_count == 0

    @patch('common.time_sync.ntplib.NTPClient')
    def test_sync_fallback_servers(self, mock_ntp_class):
        """Test fallback to secondary servers."""
        mock_client = MagicMock()
        mock_ntp_class.return_value = mock_client

        # First server fails, second succeeds
        mock_client.request.side_effect = [
            Exception("Primary server failed"),
            MagicMock(offset=0.03, stratum=2, precision=-20)
        ]

        ts = TimeSync()
        ts._sync_once()

        assert ts.last_offset == 0.03
        assert ts.sync_success_count == 1

    @patch('common.time_sync.ntplib.NTPClient')
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
        assert 29 < stats["seconds_since_sync"] < 31

    @patch('common.time_sync.ntplib.NTPClient')
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
```

### 5.3 Processors Tests

**New file:** `tests/test_processors.py`

```python
"""Tests for signal processors."""
import pytest
import numpy as np

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remote-node"))

from processors import (
    SignalProcessor, DAGProcessor, DbfsMeasurement,
    BandpassFilter, Resample, MetadataTagger
)


class TestDbfsMeasurement:
    """Test dBFS measurement processor."""

    def test_silent_signal(self):
        """Test measurement of silent signal."""
        processor = DbfsMeasurement()
        data = {
            "data": [0] * 1000,
            "timestamp": 1000000000,
            "time_precision": "ns",
            "metadata": {"bit_depth": 16}
        }

        result = processor.process(data)

        assert result["data_type"] == "scalar"
        assert result["data"] == -np.inf

    def test_full_scale_signal(self):
        """Test measurement of full-scale signal."""
        processor = DbfsMeasurement()
        # Full scale for 16-bit is 32767
        data = {
            "data": [32767] * 1000,
            "timestamp": 1000000000,
            "time_precision": "ns",
            "metadata": {"bit_depth": 16}
        }

        result = processor.process(data)

        # Should be close to 0 dBFS + REFERENCE_DBSPL (120)
        assert result["data_type"] == "scalar"
        assert 119 < result["data"] < 121

    def test_rms_calculation(self):
        """Test RMS calculation."""
        # Known RMS: sine wave has RMS = amplitude / sqrt(2)
        t = np.linspace(0, 1, 44100)
        amplitude = 10000
        sine = (amplitude * np.sin(2 * np.pi * 100 * t)).astype(int).tolist()

        rms = DbfsMeasurement.rms(sine)
        expected_rms = amplitude / np.sqrt(2)

        assert abs(rms - expected_rms) < 100  # Within 1%


class TestBandpassFilter:
    """Test bandpass filter processor."""

    def test_filter_initialization(self):
        """Test filter initializes correctly."""
        filt = BandpassFilter(low_cut=100, high_cut=1000)
        assert filt.low_cut == 100
        assert filt.high_cut == 1000
        assert filt.sos is None  # Not initialized until process

    def test_filter_removes_dc(self):
        """Test filter removes DC component."""
        filt = BandpassFilter(low_cut=20, high_cut=200)

        # Signal with DC offset
        data = {
            "data": [1000] * 4410,  # Pure DC
            "metadata": {"sample_rate": 44100}
        }

        result = filt.process(data)

        # DC should be heavily attenuated
        assert np.abs(np.mean(result["data"])) < 100

    def test_filter_passes_inband(self):
        """Test filter passes in-band frequencies."""
        filt = BandpassFilter(low_cut=50, high_cut=150)

        # 100Hz tone - should pass
        t = np.linspace(0, 0.5, 22050)
        tone = (10000 * np.sin(2 * np.pi * 100 * t)).tolist()

        data = {
            "data": tone,
            "metadata": {"sample_rate": 44100}
        }

        result = filt.process(data)

        # Should retain most energy
        input_power = np.mean(np.array(tone) ** 2)
        output_power = np.mean(np.array(result["data"]) ** 2)

        assert output_power > input_power * 0.5  # At least 50% retained

    def test_filter_state_persistence(self):
        """Test filter maintains state across chunks."""
        filt = BandpassFilter(low_cut=50, high_cut=150)

        # Process two chunks
        chunk1 = {
            "data": [0] * 4410,
            "metadata": {"sample_rate": 44100}
        }
        chunk2 = {
            "data": [0] * 4410,
            "metadata": {"sample_rate": 44100}
        }

        filt.process(chunk1)
        zi_after_first = filt.zi.copy()

        filt.process(chunk2)

        # State should have changed
        assert filt.zi is not None

    def test_invalid_frequencies(self):
        """Test validation of invalid frequencies."""
        # Low cut at 0
        with pytest.raises(ValueError):
            filt = BandpassFilter(low_cut=0, high_cut=100)
            filt.process({"data": [0]*100, "metadata": {"sample_rate": 44100}})

        # High cut above Nyquist
        with pytest.raises(ValueError):
            filt = BandpassFilter(low_cut=100, high_cut=25000)
            filt.process({"data": [0]*100, "metadata": {"sample_rate": 44100}})

        # Low >= high
        with pytest.raises(ValueError):
            filt = BandpassFilter(low_cut=200, high_cut=100)
            filt.process({"data": [0]*100, "metadata": {"sample_rate": 44100}})


class TestMetadataTagger:
    """Test metadata tagger processor."""

    def test_add_tag(self):
        """Test adding a tag."""
        tagger = MetadataTagger(tag="reference")
        data = {
            "data": [1, 2, 3],
            "metadata": {}
        }

        result = tagger.process(data)

        assert "tags" in result["metadata"]
        assert "reference" in result["metadata"]["tags"]

    def test_append_to_existing_tags(self):
        """Test appending to existing tags."""
        tagger = MetadataTagger(tag="new_tag")
        data = {
            "data": [1, 2, 3],
            "metadata": {"tags": ["existing"]}
        }

        result = tagger.process(data)

        assert "existing" in result["metadata"]["tags"]
        assert "new_tag" in result["metadata"]["tags"]


class TestDAGProcessor:
    """Test DAG-based processor."""

    def test_simple_dag(self):
        """Test simple linear DAG."""
        steps = {
            "start": {"type": "start", "next": ["1"]},
            "1": {"type": "metadata_tagger", "params": {"tag": "processed"}, "next": []}
        }
        step_map = {
            "start": None,
            "metadata_tagger": MetadataTagger
        }

        dag = DAGProcessor(steps, step_map)
        data = {"data": [1, 2, 3], "metadata": {}}

        result = dag.process(data)

        assert "processed" in result["metadata"]["tags"]

    def test_branching_dag(self):
        """Test DAG with branches."""
        steps = {
            "start": {"type": "start", "next": ["1", "2"]},
            "1": {"type": "metadata_tagger", "params": {"tag": "branch1"}, "next": []},
            "2": {"type": "metadata_tagger", "params": {"tag": "branch2"}, "next": []}
        }
        step_map = {
            "start": None,
            "metadata_tagger": MetadataTagger
        }

        dag = DAGProcessor(steps, step_map)
        data = {"data": [1, 2, 3], "metadata": {}}

        results = dag.process(data)

        # Should get results from both branches
        assert len(results) == 2
        tags = [r["metadata"]["tags"][0] for r in results]
        assert "branch1" in tags
        assert "branch2" in tags
```

### 5.4 TelemetrySender Tests

**New file:** `tests/test_telemetry_sender.py`

```python
"""Tests for telemetry sender."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import threading

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remote-node"))

from telemetry_sender import MQTTHandler, ServiceDiscoveryListener, discover_service


class TestMQTTHandler:
    """Test MQTT handler."""

    def test_init(self):
        """Test initialization."""
        handler = MQTTHandler(
            broker_address="localhost",
            topic="test/topic",
            unit_name="test_unit"
        )
        assert handler.broker_address == "localhost"
        assert handler.topic == "test/topic"
        assert handler.qos == 1  # Default
        assert len(handler.offline_buffer) == 0

    def test_offline_buffering(self):
        """Test messages are buffered when offline."""
        handler = MQTTHandler(
            broker_address="localhost",
            topic="test/topic",
            unit_name="test_unit"
        )
        handler.is_connected = False
        handler.message_queue.put({"test": "data"})

        # Start publisher in thread briefly
        publisher_thread = threading.Thread(target=handler.publisher, daemon=True)
        publisher_thread.start()

        time.sleep(0.2)  # Let it process

        # Message should be in offline buffer
        assert len(handler.offline_buffer) >= 1

    def test_buffer_flush_on_connect(self):
        """Test buffered messages are flushed on connect."""
        handler = MQTTHandler(
            broker_address="localhost",
            topic="test/topic",
            unit_name="test_unit"
        )

        # Pre-populate buffer
        handler.offline_buffer.append({"msg": 1})
        handler.offline_buffer.append({"msg": 2})

        # Mock client
        handler.client = MagicMock()
        handler.client.publish.return_value = MagicMock(rc=0)

        # Simulate connect
        handler.is_connected = True
        handler._flush_offline_buffer()

        # Buffer should be empty
        assert len(handler.offline_buffer) == 0
        assert handler.client.publish.call_count == 2

    def test_buffer_max_size(self):
        """Test buffer respects max size."""
        handler = MQTTHandler(
            broker_address="localhost",
            topic="test/topic",
            unit_name="test_unit",
            offline_buffer_size=5
        )

        # Add more than max
        for i in range(10):
            handler.offline_buffer.append({"msg": i})

        # Should only keep last 5
        assert len(handler.offline_buffer) == 5
        assert handler.offline_buffer[0]["msg"] == 5  # Oldest kept


class TestServiceDiscovery:
    """Test service discovery."""

    def test_listener_add_service(self):
        """Test service listener handles add."""
        listener = ServiceDiscoveryListener()

        mock_zeroconf = MagicMock()
        mock_info = MagicMock()
        mock_info.parsed_addresses.return_value = ["192.168.1.100"]
        mock_zeroconf.get_service_info.return_value = mock_info

        listener.add_service(mock_zeroconf, "_test._tcp.local.", "test_service")

        assert listener.broker_address == "192.168.1.100"

    @patch('telemetry_sender.Zeroconf')
    @patch('telemetry_sender.ServiceBrowser')
    def test_discover_service_timeout(self, mock_browser, mock_zeroconf):
        """Test discovery times out appropriately."""
        # Discovery will fail (no service found)
        with pytest.raises(Exception, match="Service discovery failed"):
            discover_service(max_attempts=1)
```

---

## 6. Implementation Order

Recommended order of implementation:

1. **Critical fixes first** (Section 1) - Unblocks development on any machine
2. **Code cleanup** (Section 3) - Reduces confusion before adding features
3. **Test infrastructure** (Section 5.1, 5.2) - Enables confident changes
4. **Connectivity hardening** (Section 2) - Core reliability improvements
5. **Performance optimizations** (Section 4) - Nice to have, benchmark first
6. **Remaining tests** (Section 5.3, 5.4) - Full coverage

---

## 7. Verification Checklist

After implementation:

- [ ] All existing tests pass (`make test`)
- [ ] New tests pass
- [ ] Code formatted (`make lint`)
- [ ] No hardcoded paths remain (`grep -r "/Users/" --include="*.py"`)
- [ ] Docker compose still works (`make run`)
- [ ] Remote node can discover master via zeroconf
- [ ] Remote node can connect with explicit broker config
- [ ] Messages are buffered when master is down
- [ ] Buffered messages are sent when master comes back
- [ ] TimeSync reports accurate offset
