# Changelog

All notable changes to the Bass Sentry project.

## [2.0.0] - 2024-12-06 - Major Bug Fixes & Feature Completion

### 🎉 **CORE FEATURES NOW WORKING**

This release fixes critical bugs that prevented the cross-correlation feature from ever working correctly.

### Fixed 🐛

#### Critical Fixes
- **Cross-Correlation Feature** (`master-node/data_handler.py`):
  - Fixed `ChunkToCCStream.process()` to actually return correlation results (was returning None)
  - Rewrote timestamp alignment logic to work with chunked data instead of per-sample timestamps
  - Fixed correlation delay detection using `scipy.signal.correlate` for correct lag handling
  - Added proper handling of multiple remote nodes simultaneously
  - Now returns `(remote_id, db, tau, correlation_coef)` tuples as expected
  - Added comprehensive error handling and logging

- **Signal Generator** (`common/signals.py`):
  - Fixed array shape mismatch in `generate_reference_and_remote()` (line 198-208)
  - Now properly pads/trims noise to match signal length exactly
  - Eliminates "operands could not be broadcast" errors

- **Buffer Overflow Protection** (`remote-node/remote_node.py`):
  - Added `MAX_QUEUE_SIZE = 60` limit to prevent memory exhaustion
  - Implemented queue fullness detection with warning at 80%
  - Added dropped chunk detection via timestamp continuity monitoring
  - Changed from unbounded queue to bounded queue (maxsize=60)
  - Prevents remote node crashes from memory exhaustion

- **Typo Fix** (`remote-node/processors.py`):
  - Fixed `REFERECE_DBSPL` → `REFERENCE_DBSPL` (typo in constant name)

#### Improvements to Cross-Correlation
- Signal centering (remove DC offset) for better correlation
- Float64 precision for numerical stability
- Proper wraparound handling for delays
- Pearson correlation coefficient calculation for quality metrics
- Logging of correlation results (dB, delay, coefficient)
- Graceful handling of edge cases (empty signals, invalid inputs)

### Added ✨

#### Comprehensive Test Suite
- **14 new unit tests** for `ChunkToCCStream` processor (`tests/test_data_handler.py`):
  - Initialization and configuration
  - Reference and remote stream buffering
  - Correlation with identical signals (validates 0 delay)
  - Correlation with delayed signals
  - Multiple remote node handling
  - Buffer eviction (FIFO)
  - Timestamp gap detection
  - RCC method validation
  - Error handling for invalid inputs

#### Enhanced Logging & Monitoring
- Added structured logging for correlation results
- Added queue health monitoring with warnings
- Added dropped chunk tracking with statistics
- Added timestamp drift monitoring

#### Documentation
- Created `ARCHITECTURE_IMPROVEMENTS.md` (comprehensive 500+ line guide)
  - Technology stack assessment
  - Library recommendations
  - Performance optimization strategies
  - Reliability patterns (circuit breakers, health checks)
  - Testing strategy
  - Deployment best practices
  - Future enhancement roadmap
- Created this `CHANGELOG.md`

### Changed 🔄

#### API Changes
- `ChunkToCCStream.rcc()` now returns `(db, tau, correlation_coef)` instead of `(db, tau)`
- `create_point()` in `data_handler.py` now writes additional fields to InfluxDB:
  - `delay_seconds`: Time delay in seconds
  - `delay_ms`: Time delay in milliseconds
  - `correlation_coef`: Pearson correlation coefficient

#### Behavior Changes
- Reference stream processing now explicitly returns `None` (no correlation when updating reference)
- Remote stream processing computes correlation for ALL active remotes, not just first match
- Correlation requires at least 1 common timestamp (was 2, overly strict)
- Timestamp continuity check uses chunk-level timing, not sample-level

### Test Results 📊

```
tests/test_cross_correlation_integration.py: 5/5 passing ✅
tests/test_data_handler.py:                 14/14 passing ✅
tests/test_signals.py:                       15/15 passing ✅
---
TOTAL:                                       34/34 passing ✅ (100%)
```

### Performance

No significant performance changes. FFT-based correlation remains O(n log n) as before.

### Breaking Changes ⚠️

1. `ChunkToCCStream.rcc()` return signature changed (added correlation_coef)
2. InfluxDB schema change: added `delay_seconds`, `delay_ms`, `correlation_coef` fields
3. Existing InfluxDB dashboards may need updates to use new fields

### Migration Guide

If upgrading from previous version:

1. **InfluxDB**:
   - New fields are additive, existing data is not affected
   - Update Grafana dashboards to use new `delay_ms` and `correlation_coef` fields

2. **Configuration**:
   - No configuration changes required
   - Optionally adjust `MAX_QUEUE_SIZE` in `remote_node.py` for your use case

3. **Code**:
   - If you're calling `rcc()` directly, update to unpack 3 values instead of 2:
     ```python
     # Old
     db, tau = processor.rcc(sig1, sig2, fs)

     # New
     db, tau, correlation_coef = processor.rcc(sig1, sig2, fs)
     ```

### Known Issues

- Resample processor still has TODO for timestamp updates (line 289-294 in `processors.py`)
- Configuration is still partially hardcoded (planned for next release)
- No structured logging yet (planned for next release)

### Dependencies

No new dependencies added. All fixes use existing libraries:
- `numpy`
- `scipy`
- `influxdb-client`
- `paho-mqtt`
- `pytest`

### Upgrade Priority

🔴 **CRITICAL** - This release fixes bugs that prevented core functionality from working.
Upgrade immediately if you are experiencing:
- Cross-correlation never producing results
- Remote nodes crashing with memory errors
- Tests failing with array shape mismatches

---

## [1.0.0] - 2023-2024 - Initial Release

### Added
- Distributed audio monitoring system
- Remote node audio capture with Raspberry Pi
- Master node correlation processing
- MQTT communication layer
- InfluxDB time-series storage
- Grafana visualization
- DAG-based audio processing pipeline
- Signal processors (DBFS, bandpass filter, resampling, etc.)
- Example DAG configurations
- Docker Compose deployment

### Known Issues (Fixed in 2.0.0)
- Cross-correlation feature not working correctly
- Buffer overflow causing crashes
- Test failures in integration tests

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/):
- MAJOR version for incompatible API changes
- MINOR version for backwards-compatible functionality
- PATCH version for backwards-compatible bug fixes

---

**Full Diff**: https://github.com/jmorris0x0/bass-sentry/compare/v1.0.0...v2.0.0
