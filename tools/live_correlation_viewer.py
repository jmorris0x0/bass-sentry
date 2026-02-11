#!/usr/bin/env python3
"""
Real-time Correlation Viewer

Visualizes cross-correlation functions in real-time to see:
- Correlation peaks (primary and echoes)
- Time delays
- Histogram of recent correlation peaks

Usage:
    python tools/live_correlation_viewer.py --influxdb-url http://localhost:8086 --bucket bass_sentry

    # Or subscribe to MQTT for live correlation
    python tools/live_correlation_viewer.py --mqtt-broker localhost --mqtt-topic correlation/#
"""

import argparse
import json
import sys
from collections import deque
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.gridspec import GridSpec

# Try to import MQTT (optional)
try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("Warning: paho-mqtt not installed. MQTT mode unavailable.")

# Try to import InfluxDB (optional)
try:
    from influxdb_client import InfluxDBClient

    INFLUXDB_AVAILABLE = True
except ImportError:
    INFLUXDB_AVAILABLE = False
    print("Warning: influxdb-client not installed. InfluxDB mode unavailable.")


class CorrelationViewer:
    """Real-time correlation function visualizer."""

    def __init__(self, max_history=20):
        self.max_history = max_history
        self.correlation_data = (
            {}
        )  # node_id -> deque of (timestamp, delay_ms, correlation_func)
        self.peak_history = {}  # node_id -> deque of delay_ms values

        # Setup plot
        self.fig = plt.figure(figsize=(16, 10))
        self.gs = GridSpec(3, 2, figure=self.fig, hspace=0.3, wspace=0.3)

        self.fig.suptitle(
            "Bass Sentry - Live Correlation Viewer", fontsize=16, fontweight="bold"
        )

        # Will be populated as nodes appear
        self.node_axes = {}
        self.histogram_ax = None

    def add_correlation_data(
        self,
        node_id,
        timestamp,
        delay_ms,
        correlation_func=None,
        correlation_coef=None,
        confidence=None,
        data_quality=None,
    ):
        """Add new correlation data for a node."""
        if node_id not in self.correlation_data:
            self.correlation_data[node_id] = deque(maxlen=self.max_history)
            self.peak_history[node_id] = deque(maxlen=100)  # More history for histogram

        self.correlation_data[node_id].append(
            {
                "timestamp": timestamp,
                "delay_ms": delay_ms,
                "correlation_func": correlation_func,
                "correlation_coef": correlation_coef,
                "confidence": confidence,
                "data_quality": data_quality,
            }
        )

        self.peak_history[node_id].append(delay_ms)

    def update_plot(self, frame):
        """Update the plot with latest data."""
        self.fig.clear()

        if not self.correlation_data:
            ax = self.fig.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                "Waiting for correlation data...",
                ha="center",
                va="center",
                fontsize=14,
            )
            return

        num_nodes = len(self.correlation_data)

        # Create subplots for each node
        for idx, (node_id, data_queue) in enumerate(self.correlation_data.items()):
            if not data_queue:
                continue

            latest = data_queue[-1]

            # Correlation function plot (if available)
            if latest["correlation_func"] is not None:
                ax_corr = self.fig.add_subplot(self.gs[idx, 0])

                corr_func = latest["correlation_func"]
                time_axis = (
                    np.arange(len(corr_func)) / 44.1
                )  # Assuming 44.1kHz, convert to ms
                time_axis = time_axis - len(corr_func) / 2 / 44.1  # Center at 0

                ax_corr.plot(time_axis, corr_func, linewidth=1, alpha=0.7)
                ax_corr.axvline(
                    latest["delay_ms"],
                    color="red",
                    linestyle="--",
                    label=f"Peak: {latest['delay_ms']:.1f}ms",
                )
                ax_corr.set_xlabel("Time Lag (ms)")
                ax_corr.set_ylabel("Correlation")
                ax_corr.set_title(f"{node_id} - Correlation Function")
                ax_corr.legend()
                ax_corr.grid(True, alpha=0.3)

                # Mark any secondary peaks (echoes)
                # Find peaks above 50% of max
                threshold = 0.5 * np.max(np.abs(corr_func))
                peaks = []
                for i in range(1, len(corr_func) - 1):
                    if abs(corr_func[i]) > threshold:
                        if abs(corr_func[i]) > abs(corr_func[i - 1]) and abs(
                            corr_func[i]
                        ) > abs(corr_func[i + 1]):
                            peaks.append(time_axis[i])

                for peak_time in peaks:
                    if abs(peak_time - latest["delay_ms"]) > 5:  # Not the main peak
                        ax_corr.axvline(
                            peak_time,
                            color="orange",
                            linestyle=":",
                            alpha=0.5,
                            label="Echo",
                        )

            # Peak history plot
            ax_hist = self.fig.add_subplot(self.gs[idx, 1])

            peak_hist = list(self.peak_history[node_id])
            if peak_hist:
                ax_hist.hist(
                    peak_hist, bins=30, alpha=0.7, color="blue", edgecolor="black"
                )
                ax_hist.axvline(
                    latest["delay_ms"],
                    color="red",
                    linestyle="--",
                    label=f"Current: {latest['delay_ms']:.1f}ms",
                )
                ax_hist.set_xlabel("Time Delay (ms)")
                ax_hist.set_ylabel("Frequency")
                ax_hist.set_title(
                    f"{node_id} - Peak Histogram (last {len(peak_hist)} measurements)"
                )
                ax_hist.legend()
                ax_hist.grid(True, alpha=0.3, axis="y")

                # Add stats
                mean_delay = np.mean(peak_hist)
                std_delay = np.std(peak_hist)
                distance_m = mean_delay * 0.343
                ax_hist.text(
                    0.98,
                    0.98,
                    f"Mean: {mean_delay:.1f}ms ± {std_delay:.1f}ms\n"
                    f"Distance: {distance_m:.1f}m\n"
                    f"Quality: {latest.get('data_quality', 0)*100:.0f}%\n"
                    f"Confidence: {latest.get('confidence', 0):.2f}",
                    transform=ax_hist.transAxes,
                    verticalalignment="top",
                    horizontalalignment="right",
                    bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
                    fontsize=9,
                )

        self.fig.canvas.draw()


class MQTTCorrelationSource:
    """Subscribe to MQTT correlation results."""

    def __init__(self, viewer, broker, port=1883, topic="correlation/#"):
        self.viewer = viewer
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.client.connect(broker, port, 60)
        self.topic = topic

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"Connected to MQTT broker with result code {reason_code}")
        self.client.subscribe(self.topic)
        print(f"Subscribed to {self.topic}")

    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())

            # Extract correlation data
            node_id = data.get("station_id", "unknown")
            timestamp = data.get("timestamp", 0)
            delay_ms = data.get("delay_ms", 0)
            correlation_coef = data.get("correlation_coef", 0)
            confidence = data.get("confidence", 0)
            data_quality = data.get("data_quality", 1.0)

            # Note: Full correlation function typically not transmitted via MQTT
            # Only summary statistics

            self.viewer.add_correlation_data(
                node_id,
                timestamp,
                delay_ms,
                correlation_func=None,  # Not available via MQTT
                correlation_coef=correlation_coef,
                confidence=confidence,
                data_quality=data_quality,
            )

        except Exception as e:
            print(f"Error processing MQTT message: {e}")

    def start(self):
        """Start MQTT loop in background."""
        self.client.loop_start()


class InfluxDBCorrelationSource:
    """Query InfluxDB for historical correlation data."""

    def __init__(self, viewer, url, token, org, bucket):
        self.viewer = viewer
        self.client = InfluxDBClient(url=url, token=token, org=org)
        self.query_api = self.client.query_api()
        self.bucket = bucket
        self.org = org

    def query_recent(self, time_range="-5m"):
        """Query recent correlation data."""
        query = f"""
        from(bucket: "{self.bucket}")
          |> range(start: {time_range})
          |> filter(fn: (r) => r._measurement == "correlation")
          |> filter(fn: (r) => r._field == "delay_ms" or
                              r._field == "correlation_coef" or
                              r._field == "confidence" or
                              r._field == "data_quality")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """

        try:
            result = self.query_api.query(query, org=self.org)

            for table in result:
                for record in table.records:
                    node_id = record.values.get("station_id", "unknown")
                    timestamp = record.get_time()

                    self.viewer.add_correlation_data(
                        node_id=node_id,
                        timestamp=timestamp,
                        delay_ms=record.values.get("delay_ms", 0),
                        correlation_func=None,  # Full function not stored in InfluxDB
                        correlation_coef=record.values.get("correlation_coef", 0),
                        confidence=record.values.get("confidence", 0),
                        data_quality=record.values.get("data_quality", 1.0),
                    )

        except Exception as e:
            print(f"Error querying InfluxDB: {e}")


def main():
    parser = argparse.ArgumentParser(description="Real-time correlation viewer")
    parser.add_argument(
        "--mode",
        choices=["mqtt", "influxdb", "demo"],
        default="demo",
        help="Data source mode",
    )

    # MQTT options
    parser.add_argument(
        "--mqtt-broker", default="localhost", help="MQTT broker address"
    )
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--mqtt-topic", default="correlation/#", help="MQTT topic to subscribe"
    )

    # InfluxDB options
    parser.add_argument(
        "--influxdb-url", default="http://localhost:8086", help="InfluxDB URL"
    )
    parser.add_argument("--influxdb-token", default="", help="InfluxDB token")
    parser.add_argument(
        "--influxdb-org", default="bass-sentry", help="InfluxDB organization"
    )
    parser.add_argument(
        "--influxdb-bucket", default="bass_sentry", help="InfluxDB bucket"
    )

    args = parser.parse_args()

    # Create viewer
    viewer = CorrelationViewer(max_history=20)

    # Setup data source
    if args.mode == "mqtt":
        if not MQTT_AVAILABLE:
            print("Error: paho-mqtt not installed. Install with: pip install paho-mqtt")
            sys.exit(1)
        source = MQTTCorrelationSource(
            viewer, args.mqtt_broker, args.mqtt_port, args.mqtt_topic
        )
        source.start()

    elif args.mode == "influxdb":
        if not INFLUXDB_AVAILABLE:
            print(
                "Error: influxdb-client not installed. Install with: pip install influxdb-client"
            )
            sys.exit(1)
        source = InfluxDBCorrelationSource(
            viewer,
            args.influxdb_url,
            args.influxdb_token,
            args.influxdb_org,
            args.influxdb_bucket,
        )
        # Query once for initial data
        source.query_recent()

    elif args.mode == "demo":
        # Demo mode with synthetic data
        import time

        def generate_demo_data():
            while True:
                for node in ["dance_floor", "back_bar", "side_wall"]:
                    delay = 30 + np.random.randn() * 2  # Simulate varying delay

                    # Generate synthetic correlation function
                    t = np.linspace(-100, 100, 8820)  # ±100ms
                    corr = (
                        np.exp(-((t - delay) ** 2) / 50)
                        * np.cos(2 * np.pi * 50 * t / 1000)
                        * 1000
                    )
                    corr += np.random.randn(len(corr)) * 100  # Add noise

                    viewer.add_correlation_data(
                        node_id=node,
                        timestamp=time.time(),
                        delay_ms=delay,
                        correlation_func=corr,
                        correlation_coef=0.8 + np.random.randn() * 0.1,
                        confidence=0.75 + np.random.randn() * 0.1,
                        data_quality=0.95 + np.random.randn() * 0.05,
                    )
                time.sleep(1)

        import threading

        demo_thread = threading.Thread(target=generate_demo_data, daemon=True)
        demo_thread.start()

    # Start animation
    ani = FuncAnimation(
        viewer.fig, viewer.update_plot, interval=1000, cache_frame_data=False
    )
    plt.show()


if __name__ == "__main__":
    main()
