#!/usr/bin/env python3
"""
Bass Sentry Web Dashboard Server

Provides a web interface for real-time monitoring of sound levels,
cross-correlation visualizations, distance radar, and node health.

Features WebSocket for live correlation waveform streaming.

Run with: python web/server.py
Or via Docker: integrated into master-node container
"""

# Eventlet monkey patching must happen before any other imports
import eventlet
eventlet.monkey_patch()

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, send_from_directory, request
from flask_socketio import SocketIO, emit

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from master_node.correlation import CORRELATION_IMAGE_DIR, get_latest_correlation_data
except ImportError:
    # Fallback for when running standalone
    CORRELATION_IMAGE_DIR = os.environ.get(
        "CORRELATION_IMAGE_DIR", "/tmp/bass-sentry/correlation_images"
    )

    def get_latest_correlation_data():
        result = {}
        if not os.path.exists(CORRELATION_IMAGE_DIR):
            return result
        for filename in os.listdir(CORRELATION_IMAGE_DIR):
            if filename.endswith(".png"):
                filepath = os.path.join(CORRELATION_IMAGE_DIR, filename)
                remote_id = filename[:-4]
                stat = os.stat(filepath)
                result[remote_id] = {
                    "path": filepath,
                    "filename": filename,
                    "modified": stat.st_mtime,
                    "size": stat.st_size,
                }
        return result


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", template_folder="templates")
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "mytoken")
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "myorg")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "mybucket")

# Node configuration for venue map (can be overridden by config file)
DEFAULT_NODES = {
    "stage": {"x": 0, "y": 0, "type": "reference", "label": "Stage"},
    "dance_floor": {"x": 15, "y": 10, "type": "remote", "label": "Dance Floor"},
    "back_bar": {"x": 40, "y": 0, "type": "remote", "label": "Back Bar"},
    "neighbor": {"x": 100, "y": 30, "type": "remote", "label": "Neighbor"},
}


def get_node_config():
    """Load node configuration from file or environment."""
    config_path = os.environ.get("NODE_CONFIG_PATH", "config/nodes.json")
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load node config: {e}")
    return DEFAULT_NODES


def get_influx_client():
    """Get InfluxDB client for querying data."""
    try:
        from influxdb_client import InfluxDBClient
        return InfluxDBClient(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
        )
    except ImportError:
        logger.warning("influxdb_client not available")
        return None
    except Exception as e:
        logger.error(f"Failed to create InfluxDB client: {e}")
        return None


@app.route("/")
def index():
    """Serve the main dashboard."""
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/api/nodes")
def api_nodes():
    """Get node configuration for venue map."""
    return jsonify(get_node_config())


@app.route("/api/correlation-images")
def api_correlation_images():
    """Get list of available correlation images."""
    images = get_latest_correlation_data()
    # Convert to list with age info
    result = []
    now = time.time()
    for remote_id, info in images.items():
        age_seconds = now - info["modified"]
        result.append({
            "remote_id": remote_id,
            "filename": info["filename"],
            "age_seconds": age_seconds,
            "modified": datetime.fromtimestamp(info["modified"]).isoformat(),
            "stale": age_seconds > 30,  # Mark as stale if > 30 seconds old
        })
    return jsonify(result)


@app.route("/correlation/<filename>")
def serve_correlation_image(filename):
    """Serve a correlation waveform image."""
    return send_from_directory(CORRELATION_IMAGE_DIR, filename)


@app.route("/api/distances")
def api_distances():
    """Get latest distance measurements from InfluxDB."""
    client = get_influx_client()
    if not client:
        return jsonify({"error": "InfluxDB not available"}), 503

    try:
        query_api = client.query_api()
        query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
            |> range(start: -5m)
            |> filter(fn: (r) => r["_measurement"] == "cross_correlation")
            |> filter(fn: (r) => r["_field"] == "delay_ms")
            |> group(columns: ["remote_id"])
            |> last()
        '''
        tables = query_api.query(query, org=INFLUXDB_ORG)

        distances = []
        for table in tables:
            for record in table.records:
                distances.append({
                    "remote_id": record.values.get("remote_id", "unknown"),
                    "delay_ms": record.get_value(),
                    "distance_m": record.get_value() * 0.343,
                    "timestamp": record.get_time().isoformat() if record.get_time() else None,
                })
        return jsonify(distances)
    except Exception as e:
        logger.error(f"Failed to query distances: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        client.close()


@app.route("/api/venue-contribution")
def api_venue_contribution():
    """Get venue contribution data for all remote stations.

    Returns comprehensive data including:
    - venue_db: Venue's dB contribution (noise-corrected)
    - total_db: Total measured dB at remote
    - la90: Background level (90th percentile)
    - venue_audibility: How much venue exceeds background
    - distance_m: Distance from reference
    - correlation_coef: Correlation strength (confidence indicator)
    """
    client = get_influx_client()
    if not client:
        return jsonify({"error": "InfluxDB not available"}), 503

    try:
        query_api = client.query_api()
        # Query all relevant fields from cross_correlation
        query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
            |> range(start: -5m)
            |> filter(fn: (r) => r["_measurement"] == "cross_correlation")
            |> filter(fn: (r) => r["_field"] == "venue_db" or
                                r["_field"] == "total_db" or
                                r["_field"] == "la90" or
                                r["_field"] == "venue_audibility" or
                                r["_field"] == "delay_ms" or
                                r["_field"] == "correlation_coef")
            |> group(columns: ["remote_id", "_field"])
            |> last()
        '''
        tables = query_api.query(query, org=INFLUXDB_ORG)

        # Aggregate data by remote_id
        station_data = {}
        for table in tables:
            for record in table.records:
                remote_id = record.values.get("remote_id", "unknown")
                field = record.values.get("_field")
                value = record.get_value()

                if remote_id not in station_data:
                    station_data[remote_id] = {
                        "remote_id": remote_id,
                        "timestamp": record.get_time().isoformat() if record.get_time() else None,
                    }

                station_data[remote_id][field] = value

        # Calculate distance from delay
        for remote_id, data in station_data.items():
            if "delay_ms" in data:
                data["distance_m"] = abs(data["delay_ms"]) * 0.343

        return jsonify(list(station_data.values()))
    except Exception as e:
        logger.error(f"Failed to query venue contribution: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        client.close()


@app.route("/api/levels")
def api_levels():
    """Get latest dB levels from InfluxDB."""
    client = get_influx_client()
    if not client:
        return jsonify({"error": "InfluxDB not available"}), 503

    try:
        query_api = client.query_api()
        query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
            |> range(start: -1m)
            |> filter(fn: (r) => r["_measurement"] == "dBSPL" or r["_measurement"] == "dB")
            |> last()
        '''
        tables = query_api.query(query, org=INFLUXDB_ORG)

        levels = []
        for table in tables:
            for record in table.records:
                levels.append({
                    "location": record.values.get("location", "unknown"),
                    "band": record.values.get("band", "full"),
                    "value": record.get_value(),
                    "timestamp": record.get_time().isoformat() if record.get_time() else None,
                })
        return jsonify(levels)
    except Exception as e:
        logger.error(f"Failed to query levels: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        client.close()


@app.route("/api/node-health")
def api_node_health():
    """Get node health status from InfluxDB (derived from dBSPL measurements)."""
    client = get_influx_client()
    if not client:
        return jsonify({"error": "InfluxDB not available"}), 503

    try:
        query_api = client.query_api()
        # Get recent measurements per location to determine node health
        query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
            |> range(start: -5m)
            |> filter(fn: (r) => r["_measurement"] == "dBSPL")
            |> group(columns: ["location"])
            |> last()
        '''
        tables = query_api.query(query, org=INFLUXDB_ORG)

        nodes = []
        now = datetime.utcnow()
        seen_locations = set()

        for table in tables:
            for record in table.records:
                location = record.values.get("location", "unknown")
                if location in seen_locations:
                    continue
                seen_locations.add(location)

                last_seen = record.get_time()
                age_seconds = (now - last_seen.replace(tzinfo=None)).total_seconds() if last_seen else 9999
                nodes.append({
                    "node_name": location,
                    "status": "connected" if age_seconds < 120 else "stale",
                    "messages_sent": 0,  # Not tracked in dBSPL
                    "messages_failed": 0,
                    "buffer_size": 0,
                    "last_seen": last_seen.isoformat() if last_seen else None,
                    "online": age_seconds < 120,
                })
        return jsonify(nodes)
    except Exception as e:
        logger.error(f"Failed to query node health: {e}")
        return jsonify([])  # Return empty array instead of error
    finally:
        client.close()


# ===================
# WebSocket handlers
# ===================

@socketio.on('connect')
def handle_connect():
    """Client connected to WebSocket."""
    logger.info(f"WebSocket client connected")
    emit('status', {'connected': True})


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected from WebSocket."""
    logger.info(f"WebSocket client disconnected")


# MQTT subscriber for live correlation data
mqtt_client = None
mqtt_thread = None


def start_mqtt_subscriber():
    """Start MQTT subscriber to forward correlation data to WebSocket clients."""
    global mqtt_client

    mqtt_host = os.environ.get("MQTT_HOST", "mosquitto")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))

    try:
        import paho.mqtt.client as mqtt

        # Use callback API version 2 for paho-mqtt 2.x
        def on_connect(client, userdata, flags, reason_code, properties):
            logger.info(f"MQTT connected with result code {reason_code}")
            # Subscribe to audio topics for correlation data
            client.subscribe("audio/#")

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                data_type = payload.get("data_type")

                if data_type == "audio_chunk":
                    # Extract waveform data for visualization
                    station_id = payload.get("station_id", "unknown")
                    audio_data = payload.get("data", [])
                    metadata = payload.get("metadata", {})

                    # Downsample for visualization (send every 10th sample)
                    if len(audio_data) > 200:
                        step = len(audio_data) // 200
                        audio_data = audio_data[::step]

                    location = metadata.get('location', station_id)
                    logger.info(f"Broadcasting waveform for {location} ({len(audio_data)} samples)")

                    # Broadcast to WebSocket clients
                    socketio.emit('waveform', {
                        'station_id': station_id,
                        'location': location,
                        'data': audio_data,
                        'is_reference': 'reference' in metadata.get('tags', []),
                        'timestamp': payload.get('timestamp', time.time())
                    })

                elif data_type == "scalar":
                    # dB level update
                    metadata = payload.get("metadata", {})
                    socketio.emit('level', {
                        'location': metadata.get('location', 'unknown'),
                        'value': payload.get('data', 0),
                        'band': f"{metadata.get('filter_low', 20)}-{metadata.get('filter_high', 200)}Hz",
                        'timestamp': payload.get('timestamp', time.time())
                    })

            except Exception as e:
                logger.warning(f"Error processing MQTT message: {e}")

        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message

        logger.info(f"Connecting to MQTT broker at {mqtt_host}:{mqtt_port}")
        mqtt_client.connect(mqtt_host, mqtt_port, 60)
        mqtt_client.loop_forever()

    except ImportError:
        logger.warning("paho-mqtt not installed, WebSocket streaming disabled")
    except Exception as e:
        logger.error(f"MQTT connection failed: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("WEB_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    logger.info(f"Starting Bass Sentry Web Dashboard on port {port}")
    logger.info(f"Correlation images directory: {CORRELATION_IMAGE_DIR}")

    # Start MQTT subscriber in background greenlet (eventlet)
    eventlet.spawn(start_mqtt_subscriber)

    # Run with SocketIO instead of plain Flask
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)
