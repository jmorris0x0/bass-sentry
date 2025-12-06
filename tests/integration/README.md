# Integration Tests

Docker-based integration tests that validate the complete Bass Sentry system.

## What Gets Tested

1. **Full pipeline**: Remote nodes → MQTT → Master node → InfluxDB
2. **Correlation accuracy**: Verifies detected delays match expected values
3. **Data quality**: Checks quality metrics are present and reasonable
4. **Confidence scores**: Validates confidence calculation
5. **System reliability**: Tests auto-recovery and error handling

## Running Integration Tests

### Quick Start
```bash
# Run full integration test suite
docker-compose -f docker-compose.test.yml up --abort-on-container-exit

# View test results
docker-compose -f docker-compose.test.yml logs test_runner
```

### Step-by-Step
```bash
# 1. Build test environment
docker-compose -f docker-compose.test.yml build

# 2. Start services
docker-compose -f docker-compose.test.yml up -d influxdb mosquitto master remote_dance_floor remote_back_bar

# 3. Wait for system to stabilize (30 seconds)
sleep 30

# 4. Run tests
docker-compose -f docker-compose.test.yml run --rm test_runner

# 5. Cleanup
docker-compose -f docker-compose.test.yml down -v
```

## Test Environment

### Services
- **InfluxDB**: Time-series database (test instance)
- **Mosquitto**: MQTT broker
- **Master**: Master node running correlation
- **remote_dance_floor**: Simulated node (32.6ms delay)
- **remote_back_bar**: Simulated node (65.2ms delay)
- **test_runner**: Pytest container

### Test Data

Simulated nodes generate chirp signals (20-200 Hz) with known delays:
- `dance_floor`: 32.6ms delay (11.2m distance)
- `back_bar`: 65.2ms delay (22.4m distance)

### Expected Results
```
tests/integration/test_full_system.py::TestFullSystemIntegration::test_influxdb_connection PASSED
tests/integration/test_full_system.py::TestFullSystemIntegration::test_correlation_data_exists PASSED
tests/integration/test_full_system.py::TestFullSystemIntegration::test_dance_floor_delay_accuracy PASSED
tests/integration/test_full_system.py::TestFullSystemIntegration::test_back_bar_delay_accuracy PASSED
tests/integration/test_full_system.py::TestFullSystemIntegration::test_data_quality_metrics PASSED
tests/integration/test_full_system.py::TestFullSystemIntegration::test_confidence_scores PASSED

========================== 6 passed in 90s ==========================
```

## Test Details

### test_influxdb_connection
Verifies InfluxDB is accessible and healthy.

### test_correlation_data_exists
Checks that correlation measurements are being written to InfluxDB within 60 seconds of startup.

### test_dance_floor_delay_accuracy
Validates detected delay for dance_floor node is within 5ms of expected 32.6ms.

### test_back_bar_delay_accuracy
Validates detected delay for back_bar node is within 5ms of expected 65.2ms.

### test_data_quality_metrics
Verifies data_quality field exists and is >0.9 (simulated environment has no packet loss).

### test_confidence_scores
Checks confidence scores are calculated and within valid range [0, 1].

## Troubleshooting

### Tests timeout
```bash
# Increase wait time in docker-compose.test.yml
command: >
  bash -c "
  sleep 60 &&  # Increase from 30 to 60
  pytest /tests/integration/ -v
  "
```

### No correlation data
```bash
# Check master node logs
docker-compose -f docker-compose.test.yml logs master

# Check simulated remote nodes
docker-compose -f docker-compose.test.yml logs remote_dance_floor

# Check MQTT traffic
docker-compose -f docker-compose.test.yml exec mosquitto mosquitto_sub -t '#' -v
```

### Correlation accuracy failures
```bash
# Check detected vs expected delays in test output
docker-compose -f docker-compose.test.yml logs test_runner | grep "Expected"

# Verify simulated node delays
docker-compose -f docker-compose.test.yml logs remote_dance_floor | grep "delay"
```

## Adding More Tests

### Test packet loss tolerance
```yaml
# Add to docker-compose.test.yml
remote_lossy_node:
  build: ./remote-node
  environment:
    - PACKET_LOSS_RATE=0.2  # 20% packet loss
```

```python
# Add to test_full_system.py
def test_packet_loss_tolerance(self, influx_client):
    """Verify system handles 20% packet loss gracefully."""
    # Query data_quality for lossy_node
    # Assert quality is 0.7-0.9 (accounts for 20% loss + interpolation)
```

### Test time drift
```yaml
remote_drifting_node:
  environment:
    - CLOCK_DRIFT_PPM=50  # Simulate 50 ppm drift
```

## CI/CD Integration

### GitHub Actions
```yaml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run integration tests
        run: |
          docker-compose -f docker-compose.test.yml up \
            --abort-on-container-exit \
            --exit-code-from test_runner
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-results
          path: test-results/
```

## Performance Benchmarks

Run with timing:
```bash
time docker-compose -f docker-compose.test.yml up --abort-on-container-exit
```

Expected:
- **Startup**: 15-20 seconds
- **First correlation**: 25-30 seconds
- **Total test time**: 60-90 seconds

## Future Enhancements

- [ ] Multi-node scaling tests (10, 50, 100 nodes)
- [ ] Network partition simulation
- [ ] Master node failover tests
- [ ] Long-running stability tests (24+ hours)
- [ ] Performance benchmarking
- [ ] Memory leak detection
