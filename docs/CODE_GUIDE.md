# Bass Sentry - Code Guide

Quick reference for understanding the codebase structure.

## Directory Structure

```
bass-sentry/
├── remote-node/          # Runs on Raspberry Pi sensors
│   ├── remote_node.py    # Entry point - captures audio, runs DAG
│   ├── processors.py     # Signal processing DAG (filter, resample, dBFS)
│   └── telemetry_sender.py  # Sends data to master via transport layer
│
├── master-node/          # Runs on central server
│   ├── master-node.py    # Entry point - starts the node manager
│   ├── node_manager.py   # Manages connections (MQTT/InfluxDB) and message routing
│   └── correlation.py    # Cross-correlation analysis between audio streams
│
├── common/               # Shared code
│   ├── transport.py      # Abstract transport layer
│   ├── transport_mqtt.py # MQTT implementation (WiFi)
│   ├── transport_lora.py # LoRa implementation (long-range)
│   ├── transport_http.py # HTTP implementation (cellular)
│   ├── transport_serial.py # Serial implementation (wired)
│   ├── time_sync.py      # NTP synchronization with drift compensation
│   └── signals.py        # Test signal generation
│
├── tests/                # Test suite
├── simulator/            # Event simulation for validation
└── docs/                 # Documentation
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REMOTE NODE (RPi)                           │
│                                                                     │
│  Microphone → [processors.py DAG] → [telemetry_sender.py]          │
│                    │                        │                       │
│              Filter/Resample           Transport                    │
│              Measure dBFS              (MQTT/LoRa/HTTP)             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         MASTER NODE                                  │
│                                                                     │
│  Transport → [node_manager.py] → [correlation.py] → InfluxDB       │
│                    │                    │                           │
│              Route messages      Cross-correlate                    │
│              Track node health   reference vs remote                │
│                                  Calculate delays                   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                              Grafana Dashboard
```

## Key Classes

### Remote Node

| File | Class | Purpose |
|------|-------|---------|
| `processors.py` | `DAGProcessor` | Executes processing pipeline from JSON config |
| `processors.py` | `BandpassFilter` | IIR Butterworth filter for frequency isolation |
| `processors.py` | `DbfsMeasurement` | Converts audio RMS to dB SPL |
| `processors.py` | `Resample` | Changes sample rate |
| `telemetry_sender.py` | `TransportHandler` | Queues messages, handles offline buffering |
| `telemetry_sender.py` | `TelemetrySender` | High-level API for sending telemetry |

### Master Node

| File | Class | Purpose |
|------|-------|---------|
| `node_manager.py` | `DataManager` | Connects to MQTT/InfluxDB, routes messages |
| `correlation.py` | `DataHandler` | Routes data to appropriate processor |
| `correlation.py` | `ChunkToCCStream` | Cross-correlation between reference and remote audio |
| `correlation.py` | `ScalarTS` | Handles scalar measurements (dB values) |

### Common

| File | Class | Purpose |
|------|-------|---------|
| `transport.py` | `Transport` | Abstract base for all transports |
| `transport.py` | `TransportConfig` | Configuration for transport selection |
| `time_sync.py` | `TimeSync` | NTP sync with drift compensation |

## Processing Pipeline (DAG)

The remote node processes audio through a configurable DAG (Directed Acyclic Graph):

```json
{
    "steps": {
        "start": {"type": "start", "next": ["filter", "measure"]},
        "filter": {
            "type": "bandpass_filter",
            "params": {"low_cut": 35, "high_cut": 250},
            "next": ["resample"]
        },
        "resample": {
            "type": "resample",
            "params": {"new_sample_rate": 500},
            "next": ["measure_filtered"]
        },
        "measure": {"type": "dbfs_measurement", "next": []},
        "measure_filtered": {"type": "dbfs_measurement", "next": []}
    }
}
```

This creates parallel processing paths from a single audio input.

## Cross-Correlation

The master node correlates audio from a "reference" node (at the stage) with "remote" nodes (in the venue):

1. **Buffer audio chunks** from all nodes (2 seconds)
2. **Align timestamps** across nodes (handles packet loss)
3. **FFT-based correlation** finds time delay between signals
4. **Calculate distance**: `delay_seconds × 343 m/s = distance_meters`

This filters out environmental noise - only sounds from the stage correlate.

## Transport Layer

Pluggable transport supports multiple communication methods:

| Transport | Use Case | Range |
|-----------|----------|-------|
| MQTT (WiFi) | Default, indoor venues | 50-100m |
| LoRa | Outdoor festivals | 2-10km |
| HTTP | Cellular/internet | Unlimited |
| Serial | Testing/debugging | 5-15m |

Select via config:
```json
{
    "transport": {
        "type": "lora",
        "lora": {"frequency": 915, "spreading_factor": 7}
    }
}
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/test_correlation.py -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

## Entry Points

| Command | What it does |
|---------|--------------|
| `python remote-node/remote_node.py config.json` | Start remote sensor node |
| `python master-node/master-node.py` | Start master node (usually via Docker) |
| `python simulator/simulate_event.py` | Run event simulation |
| `docker-compose up` | Start full stack (master + InfluxDB + Grafana) |
