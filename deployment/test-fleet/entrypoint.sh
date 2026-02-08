#!/bin/bash
# Entrypoint for fake Pi container
# Sets up fake serial number and starts the remote node

set -e

echo "==================================="
echo "Bass Sentry Fake Pi Node"
echo "==================================="
echo "Serial: $PI_SERIAL"
echo "MQTT Host: $MQTT_HOST"
echo "Graylog: ${GRAYLOG_HOST:-disabled}"
echo "==================================="

# Create fake /proc/cpuinfo with serial number
# The real Pi has this, we simulate it
mkdir -p /fake_proc
cat > /fake_proc/cpuinfo << EOF
processor       : 0
model name      : ARMv7 Processor rev 3 (v7l)
BogoMIPS        : 108.00
Features        : half thumb fastmult vfp edsp neon vfpv3 tls vfpv4 idiva idivt vfpd32 lpae evtstrm crc32
CPU implementer : 0x41
CPU architecture: 7
CPU variant     : 0x0
CPU part        : 0xd08
CPU revision    : 3

Hardware        : BCM2711
Revision        : c03111
Serial          : 10000000${PI_SERIAL}
Model           : Raspberry Pi 4 Model B Rev 1.1
EOF

# Mount the fake cpuinfo (if running with appropriate privileges)
# Otherwise, patch the Python code to read from /fake_proc
export FAKE_CPUINFO_PATH="/fake_proc/cpuinfo"

# Patch telemetry_sender to use fake cpuinfo
# This sed replaces /proc/cpuinfo with the env var path
if [ -n "$FAKE_CPUINFO_PATH" ]; then
    sed -i "s|/proc/cpuinfo|$FAKE_CPUINFO_PATH|g" /home/bass/bass-sentry/remote-node/telemetry_sender.py
    echo "Patched cpuinfo path to: $FAKE_CPUINFO_PATH"
fi

# If USE_FAKE_AUDIO is set, we need to handle the audio situation
# Create a dummy audio setup that won't crash
if [ "$USE_FAKE_AUDIO" = "true" ]; then
    echo "Fake audio mode enabled - will use synthetic data"

    # Create a wrapper script that sends synthetic data instead of real audio
    cat > /home/bass/run_fake_node.py << 'PYTHONEOF'
#!/usr/bin/env python3
"""
Fake remote node for testing - sends synthetic audio data
"""
import json
import logging
import os
import sys
import time
import numpy as np

sys.path.insert(0, '/home/bass/bass-sentry/remote-node')
sys.path.insert(0, '/home/bass/bass-sentry')

from telemetry_sender import TelemetrySender, get_node_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Graylog setup
graylog_host = os.environ.get("GRAYLOG_HOST")
if graylog_host:
    try:
        import graypy
        graylog_port = int(os.environ.get("GRAYLOG_PORT", "12201"))
        handler = graypy.GELFUDPHandler(graylog_host, graylog_port)
        handler.facility = f"bass-sentry-{get_node_id()}"
        logging.getLogger().addHandler(handler)
        logger.info(f"Graylog enabled: {graylog_host}:{graylog_port}")
    except Exception as e:
        logger.warning(f"Graylog setup failed: {e}")

def generate_fake_audio(sample_rate=44100, chunk_size=22050):
    """Generate synthetic audio that simulates real audio patterns."""
    # Generate pink noise with some variation
    t = np.linspace(0, chunk_size / sample_rate, chunk_size)

    # Base frequency varies to simulate music
    base_freq = 60 + np.random.randint(-20, 20)  # Bass frequency

    # Generate signal
    signal = np.sin(2 * np.pi * base_freq * t)
    signal += 0.5 * np.sin(2 * np.pi * base_freq * 2 * t)  # Harmonic
    signal += 0.3 * np.random.randn(chunk_size)  # Noise

    # Normalize to int16 range and convert to Python int list for JSON serialization
    signal = signal / np.max(np.abs(signal)) * 0.8
    signal = (signal * 32767).astype(np.int16)

    return [int(x) for x in signal]

def main():
    node_id = get_node_id()
    logger.info(f"Starting fake node: {node_id}")

    mqtt_host = os.environ.get("MQTT_HOST", "master")

    # Transport config - nested format required by TransportConfig.from_dict()
    transport_config = {
        "type": "mqtt",
        "mqtt": {
            "broker": mqtt_host,
            "port": 1883
        }
    }

    sender = TelemetrySender(
        transport_config=transport_config,
        topic_suffix="audio"
    )

    sample_rate = 44100
    chunk_size = 22050  # 0.5 seconds

    logger.info(f"Connected to MQTT at {mqtt_host}")
    logger.info(f"Sending fake audio data every 0.5 seconds")

    # Determine if this is a reference node
    is_reference = os.environ.get("IS_REFERENCE", "false").lower() == "true"
    tags = ["reference"] if is_reference else []

    while True:
        try:
            # Generate fake audio
            audio_data = generate_fake_audio(sample_rate, chunk_size)

            # Calculate fake dB level (convert to Python float for JSON serialization)
            rms = np.sqrt(np.mean(np.array(audio_data, dtype=np.float32) ** 2))
            db_level = float(20 * np.log10(rms / 32767 + 1e-10) + 90)  # Offset to realistic range

            timestamp_ns = int(time.time() * 1e9)

            # Send audio chunk (for cross-correlation)
            chunk_payload = {
                "data_type": "audio_chunk",
                "station_id": node_id,
                "timestamp": timestamp_ns,
                "time_precision": "ns",
                "data": audio_data,
                "metadata": {
                    "sample_rate": sample_rate,
                    "location": node_id,
                    "tags": tags
                }
            }
            sender.send_data(chunk_payload)

            # Also send scalar dB measurement
            scalar_payload = {
                "data_type": "scalar",
                "timestamp": timestamp_ns,
                "time_precision": "ns",
                "data": db_level,
                "metadata": {
                    "units": "dBSPL",
                    "location": node_id,
                    "filter_low": 20,
                    "filter_high": 200,
                    "tags": tags
                }
            }
            sender.send_data(scalar_payload)

            # Log every 10th message at INFO level so it shows in Graylog
            if int(time.time()) % 10 == 0:
                logger.info(f"[{node_id}] dB={db_level:.1f}")
            else:
                logger.debug(f"Sent chunk + dB={db_level:.1f}")

            time.sleep(0.5)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
PYTHONEOF

    chown bass:bass /home/bass/run_fake_node.py
    chmod +x /home/bass/run_fake_node.py

    echo "Starting fake node..."
    # Use -m to preserve environment variables (MQTT_HOST, GRAYLOG_HOST, etc.)
    exec su -m bass -c "cd /home/bass/bass-sentry && /home/bass/bass-sentry/venv/bin/python /home/bass/run_fake_node.py"
else
    # Try to run the real node (will likely fail without audio hardware)
    echo "Starting real node (may fail without audio hardware)..."
    exec su -m bass -c "cd /home/bass/bass-sentry/remote-node && /home/bass/bass-sentry/venv/bin/python remote_node.py dag_files/dag-filt-ds-chunk.json"
fi
