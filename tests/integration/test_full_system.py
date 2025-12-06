"""
Integration tests for full Bass Sentry system.

Tests the complete pipeline:
1. Simulated remote nodes generate audio with known delays
2. MQTT transmission
3. Master node correlation
4. InfluxDB storage
5. Verification of detected delays
"""

import os
import time
import pytest
from influxdb_client import InfluxDBClient


class TestFullSystemIntegration:
    """Test complete system with Docker compose."""

    @pytest.fixture(scope="class")
    def influx_client(self):
        """Create InfluxDB client for test."""
        url = os.getenv("INFLUXDB_URL", "http://localhost:8086")
        token = os.getenv("INFLUXDB_TOKEN", "test-token-12345")
        org = os.getenv("INFLUXDB_ORG", "bass-sentry")

        client = InfluxDBClient(url=url, token=token, org=org)
        yield client
        client.close()

    def test_influxdb_connection(self, influx_client):
        """Verify InfluxDB is accessible."""
        health = influx_client.health()
        assert health.status == "pass", "InfluxDB health check failed"

    def test_correlation_data_exists(self, influx_client):
        """Verify correlation measurements are being stored."""
        bucket = os.getenv("INFLUXDB_BUCKET", "bass_sentry")
        org = os.getenv("INFLUXDB_ORG", "bass-sentry")

        query_api = influx_client.query_api()

        # Wait for data to appear (up to 60 seconds)
        for attempt in range(12):
            query = f"""
            from(bucket: "{bucket}")
              |> range(start: -5m)
              |> filter(fn: (r) => r._measurement == "correlation")
              |> filter(fn: (r) => r._field == "delay_ms")
              |> count()
            """

            result = query_api.query(query, org=org)

            if result and len(result) > 0 and len(result[0].records) > 0:
                count = result[0].records[0].get_value()
                if count > 0:
                    print(f"Found {count} correlation measurements")
                    return  # Success!

            print(f"Attempt {attempt + 1}/12: No correlation data yet, waiting...")
            time.sleep(5)

        pytest.fail("No correlation data found after 60 seconds")

    @pytest.mark.timeout(90)
    def test_dance_floor_delay_accuracy(self, influx_client):
        """Test dance_floor node delay detection (expected: 32.6ms)."""
        bucket = os.getenv("INFLUXDB_BUCKET", "bass_sentry")
        org = os.getenv("INFLUXDB_ORG", "bass-sentry")

        query_api = influx_client.query_api()

        # Query recent measurements for dance_floor
        query = f"""
        from(bucket: "{bucket}")
          |> range(start: -2m)
          |> filter(fn: (r) => r._measurement == "correlation")
          |> filter(fn: (r) => r._field == "delay_ms")
          |> filter(fn: (r) => r.station_id == "dance_floor")
          |> last()
        """

        # Retry for up to 60 seconds
        for attempt in range(12):
            result = query_api.query(query, org=org)

            if result and len(result) > 0 and len(result[0].records) > 0:
                detected_delay = result[0].records[0].get_value()
                expected_delay = 32.6

                error_ms = abs(detected_delay - expected_delay)
                print(
                    f"dance_floor: Expected {expected_delay}ms, Got {detected_delay}ms, Error: {error_ms}ms"
                )

                # Allow 5ms tolerance
                assert (
                    error_ms < 5.0
                ), f"Delay error too large: {error_ms}ms (expected ~{expected_delay}ms)"
                return  # Success!

            print(f"Attempt {attempt + 1}/12: No dance_floor data yet...")
            time.sleep(5)

        pytest.fail("No dance_floor correlation data found")

    @pytest.mark.timeout(90)
    def test_back_bar_delay_accuracy(self, influx_client):
        """Test back_bar node delay detection (expected: 65.2ms)."""
        bucket = os.getenv("INFLUXDB_BUCKET", "bass_sentry")
        org = os.getenv("INFLUXDB_ORG", "bass-sentry")

        query_api = influx_client.query_api()

        query = f"""
        from(bucket: "{bucket}")
          |> range(start: -2m)
          |> filter(fn: (r) => r._measurement == "correlation")
          |> filter(fn: (r) => r._field == "delay_ms")
          |> filter(fn: (r) => r.station_id == "back_bar")
          |> last()
        """

        for attempt in range(12):
            result = query_api.query(query, org=org)

            if result and len(result) > 0 and len(result[0].records) > 0:
                detected_delay = result[0].records[0].get_value()
                expected_delay = 65.2

                error_ms = abs(detected_delay - expected_delay)
                print(
                    f"back_bar: Expected {expected_delay}ms, Got {detected_delay}ms, Error: {error_ms}ms"
                )

                assert (
                    error_ms < 5.0
                ), f"Delay error too large: {error_ms}ms (expected ~{expected_delay}ms)"
                return

            print(f"Attempt {attempt + 1}/12: No back_bar data yet...")
            time.sleep(5)

        pytest.fail("No back_bar correlation data found")

    def test_data_quality_metrics(self, influx_client):
        """Verify data quality metrics are present and reasonable."""
        bucket = os.getenv("INFLUXDB_BUCKET", "bass_sentry")
        org = os.getenv("INFLUXDB_ORG", "bass-sentry")

        query_api = influx_client.query_api()

        query = f"""
        from(bucket: "{bucket}")
          |> range(start: -2m)
          |> filter(fn: (r) => r._measurement == "correlation")
          |> filter(fn: (r) => r._field == "data_quality")
          |> last()
        """

        result = query_api.query(query, org=org)

        assert result and len(result) > 0, "No data_quality measurements found"

        for table in result:
            for record in table.records:
                quality = record.get_value()
                assert 0.0 <= quality <= 1.0, f"Invalid quality value: {quality}"
                # In simulation with no packet loss, quality should be near 1.0
                assert quality > 0.9, f"Low data quality: {quality}"

    def test_confidence_scores(self, influx_client):
        """Verify confidence scores are calculated."""
        bucket = os.getenv("INFLUXDB_BUCKET", "bass_sentry")
        org = os.getenv("INFLUXDB_ORG", "bass-sentry")

        query_api = influx_client.query_api()

        query = f"""
        from(bucket: "{bucket}")
          |> range(start: -2m)
          |> filter(fn: (r) => r._measurement == "correlation")
          |> filter(fn: (r) => r._field == "confidence")
          |> last()
        """

        result = query_api.query(query, org=org)

        assert result and len(result) > 0, "No confidence measurements found"

        for table in result:
            for record in table.records:
                confidence = record.get_value()
                assert (
                    0.0 <= confidence <= 1.0
                ), f"Invalid confidence value: {confidence}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
