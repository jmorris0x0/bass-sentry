# Pluggable Transport Layer

Bass Sentry supports multiple communication transports to work in different environments. Choose the transport that best fits your venue and network availability.

---

## Quick Start

### Default (WiFi/MQTT)
```python
# No configuration needed - MQTT is default
# Just ensure MQTT broker is running on master node
```

### Long Range (LoRa)
```python
# config.json
{
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "node_id": 1
    }
  }
}
```

### Remote Monitoring (HTTP/Cellular)
```python
# config.json
{
  "transport": {
    "type": "http",
    "http": {
      "base_url": "http://192.168.1.100:8080",
      "node_id": "remote-1"
    }
  }
}
```

---

## Transport Comparison

| Transport | Range | Bandwidth | Hardware | Cost | Best For |
|-----------|-------|-----------|----------|------|----------|
| **MQTT** | 50-100m | 1-100 Mb/s | Built-in WiFi | $0 | Indoor venues with WiFi |
| **LoRa** | 2-10 km | 0.3-50 kb/s | LoRa HAT | $25/node | Outdoor festivals, large venues |
| **LoRa Gateway** | 2-10 km | 0.3-50 kb/s | Gateway Pi + LoRa HATs | $60 + $25/node | **Mac/PC master node** |
| **HTTP** | Unlimited | 1-100 Mb/s | Built-in network | $0 + data | Remote monitoring, cellular |
| **Serial** | 5-15m | 9.6-115 kb/s | USB cable | $0 | Testing, debugging, wired |

**Bandwidth requirement**: 16 kb/s per node (all transports sufficient)

**Recommended for most users**: LoRa Gateway pattern (remote nodes use LoRa, master node uses MQTT)

---

## Transport Details

### 1. MQTT (WiFi/Ethernet)

**When to use**:
- Indoor venues with WiFi coverage
- Small to medium venues (< 100m)
- Reliable network available
- Multiple nodes (pub/sub architecture)

**Pros**:
- ✅ No additional hardware required
- ✅ Fastest and most reliable
- ✅ Pub/sub architecture (broadcast to all nodes)
- ✅ Well-established protocol

**Cons**:
- ❌ Limited range (50-100m indoor)
- ❌ Requires WiFi network
- ❌ Poor wall penetration (concrete, metal)

**Hardware**: None (built-in WiFi on Raspberry Pi)

**Configuration**:
```json
{
  "transport": {
    "type": "mqtt",
    "mqtt": {
      "broker": "192.168.1.100",
      "port": 1883,
      "qos": 1,
      "keepalive": 60
    }
  }
}
```

**With authentication**:
```json
{
  "transport": {
    "type": "mqtt",
    "mqtt": {
      "broker": "mqtt.example.com",
      "port": 1883,
      "qos": 1,
      "username": "bass-sentry",
      "password": "your-password",
      "keepalive": 60
    }
  }
}
```

**Setup**:
1. Install MQTT broker on master node: `sudo apt-get install mosquitto`
2. Start broker: `sudo systemctl start mosquitto`
3. Configure remote nodes to connect to master node IP

---

### 2. LoRa (Long Range Radio)

**When to use**:
- Outdoor festivals (2-10km range)
- Large venues without WiFi
- Concrete/metal buildings (better penetration)
- Multiple buildings on campus
- Areas with poor WiFi coverage

**Pros**:
- ✅ Long range (2-10 km outdoor, 1-2 km urban)
- ✅ Better wall penetration than WiFi
- ✅ No WiFi network required
- ✅ Low power consumption
- ✅ Perfect bandwidth for bass monitoring (16 kb/s)

**Cons**:
- ❌ Requires additional hardware ($25/node)
- ❌ Lower bandwidth than WiFi (but sufficient)
- ❌ Requires line-of-sight for best performance
- ❌ Region-specific frequencies (915 MHz US, 868 MHz EU, 433 MHz Asia)

**Hardware Options**:
- **Dragino LoRa/GPS HAT** ($25) - Recommended
- **RAK Wireless LoRa Module** ($20-40)
- **Adafruit RFM95W** ($20)

**Frequency by region**:
- **US/Canada/South America**: 915 MHz
- **Europe**: 868 MHz
- **Asia**: 433 MHz

**Two Deployment Patterns**:

#### Pattern A: LoRa Gateway (Recommended for Mac/PC Master Node) ⭐

```
Remote Nodes (LoRa) → Gateway Pi → MQTT → Mac/PC Master Node
```

**Why this is better**:
- ✅ Master node stays on Mac/PC (no LoRa hardware needed)
- ✅ Easy development (Grafana/InfluxDB on Mac)
- ✅ Gateway Pi is cheap ($60: Pi Zero W + LoRa HAT)
- ✅ Remote nodes get full LoRa range (2-10 km)

**See**: `docs/LORA_GATEWAY.md` for complete setup guide

#### Pattern B: Direct LoRa (All Nodes Have LoRa HATs)

```
Remote Nodes (LoRa) → Master Node (LoRa HAT)
```

**Configuration (US)** - with network isolation & encryption:
```json
{
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "network_id": 0xA3,
      "encryption_key": "a7f3c9e1b4d8f2a6c3e7b1d5f9a4c8e2",
      "tx_power": 20,
      "spreading_factor": 7,
      "bandwidth": 125000,
      "node_id": 1,
      "gateway_id": 0
    }
  }
}
```

**Security**: Generate unique credentials per venue:
```bash
python tools/generate_lora_network.py --venue "My Venue"
```

**Network Isolation**:
- `network_id` (sync word): Hardware-level filtering - different networks can't hear each other
- `encryption_key`: AES-128 encryption - even if they could hear, can't decrypt

**Multi-Venue Deployment**: Each venue generates random credentials → zero interference even within same city!

**For maximum range** (5-20 km):
```json
{
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "tx_power": 23,
      "spreading_factor": 12,
      "bandwidth": 125000,
      "node_id": 1,
      "gateway_id": 0
    }
  }
}
```

**Spreading Factor guide**:
- **SF7**: Fastest, shortest range (1-2 km)
- **SF8-10**: Balanced speed/range (2-5 km)
- **SF12**: Maximum range, slowest (5-20 km) - still fast enough for bass!

**Range estimation**:
- **Urban** (lots of obstacles): 1-2 km (SF7), 2-5 km (SF12)
- **Suburban** (some obstacles): 2-5 km (SF7), 5-10 km (SF12)
- **Rural** (line-of-sight): 5-10 km (SF7), 10-20 km (SF12)

**Setup**:
1. Install LoRa HAT on Raspberry Pi
2. Install library: `pip install adafruit-circuitpython-rfm9x`
3. Configure frequency for your region
4. Set unique `node_id` for each node
5. Set `gateway_id` to master node ID (usually 0)

**Antenna considerations**:
- Use included antenna (usually 3-5 dBi)
- Mount antenna vertically for best coverage
- Elevate antenna for longer range
- Avoid metal/concrete obstructions

---

### 3. HTTP (Cellular/Internet)

**When to use**:
- Remote monitoring (neighbor's house)
- Cellular connectivity (5G hotspot)
- Cloud deployments
- Unlimited range needed
- Internet available but no local network

**Pros**:
- ✅ Unlimited range (anywhere with internet)
- ✅ No additional hardware required
- ✅ Works over cellular (4G/5G)
- ✅ Can use cloud servers

**Cons**:
- ❌ Requires internet connection
- ❌ Data costs (cellular)
- ❌ Polling-based (slightly higher latency)
- ❌ Requires HTTP server running

**Hardware**: None (uses built-in WiFi/Ethernet/cellular)

**Configuration**:
```json
{
  "transport": {
    "type": "http",
    "http": {
      "base_url": "http://192.168.1.100:8080",
      "node_id": "remote-1",
      "poll_interval": 0.5,
      "timeout": 5
    }
  }
}
```

**With authentication**:
```json
{
  "transport": {
    "type": "http",
    "http": {
      "base_url": "https://bass-sentry.example.com",
      "node_id": "remote-1",
      "poll_interval": 0.5,
      "timeout": 5,
      "auth_token": "your-secret-token"
    }
  }
}
```

**Setup**:
1. Run HTTP server on master node (see `common/transport_http.py` for Flask example)
2. Configure remote nodes with server URL
3. Ensure firewall allows HTTP traffic (port 8080)

**Data usage**:
- ~2 KB per message
- 2 messages/second = ~350 MB/month per node
- Minimal data usage (fits most cellular plans)

---

### 4. Serial (Wired)

**When to use**:
- Direct wired connection
- Testing and debugging
- Development
- Reliable short-distance communication
- No wireless interference concerns

**Pros**:
- ✅ No wireless interference
- ✅ Reliable and deterministic
- ✅ No additional hardware (USB cable)
- ✅ Perfect for debugging

**Cons**:
- ❌ Very short range (5-15m)
- ❌ Requires physical cable
- ❌ Point-to-point only (no broadcast)

**Hardware**: USB cable or USB-to-serial adapter

**Configuration**:
```json
{
  "transport": {
    "type": "serial",
    "serial": {
      "port": "/dev/ttyUSB0",
      "baudrate": 115200,
      "timeout": 1.0,
      "node_id": 1
    }
  }
}
```

**Windows**:
```json
{
  "transport": {
    "type": "serial",
    "serial": {
      "port": "COM3",
      "baudrate": 115200,
      "timeout": 1.0,
      "node_id": 1
    }
  }
}
```

**Setup**:
1. Connect USB cable between nodes
2. Find port name: `ls /dev/ttyUSB*` (Linux) or Device Manager (Windows)
3. Configure port in config file
4. Install library: `pip install pyserial`

**Finding serial ports**:
```python
from common.transport_serial import list_serial_ports
ports = list_serial_ports()
for port in ports:
    print(f"{port['device']}: {port['description']}")
```

---

## Choosing a Transport

### By Venue Type

| Venue Type | Recommended Transport | Alternative |
|------------|----------------------|-------------|
| Small indoor venue (< 50m) | MQTT (WiFi) | Serial (testing) |
| Medium indoor venue (50-100m) | MQTT (WiFi) | LoRa (if poor WiFi) |
| Large indoor venue (100m+) | LoRa | MQTT (with WiFi extenders) |
| Outdoor festival | LoRa | HTTP (cellular) |
| Multiple buildings | LoRa (if < 10km) | HTTP (internet) |
| Concrete/metal building | LoRa | MQTT (with mesh WiFi) |
| Remote monitoring | HTTP (cellular/internet) | LoRa (if < 10km) |
| Testing/development | Serial | MQTT (local) |

### By Range

- **< 50m**: MQTT or Serial
- **50-100m**: MQTT
- **100m-2km**: LoRa (SF7)
- **2-10km**: LoRa (SF8-SF12)
- **> 10km**: HTTP (cellular/internet)

### By Network Availability

- **WiFi available**: MQTT
- **No WiFi, outdoor**: LoRa
- **No WiFi, indoor**: LoRa (better wall penetration)
- **Internet available**: HTTP
- **No wireless allowed**: Serial

---

## Mixing Transports

You can use different transports for different nodes:

**Example**: Master node with WiFi, remote nodes with LoRa
```
Remote Node 1 (LoRa) ──┐
Remote Node 2 (LoRa) ──┼── Gateway (LoRa) ── Master Node (WiFi) ── Dashboard
Remote Node 3 (LoRa) ──┘
```

**Example**: Local MQTT + remote HTTP monitoring
```
Local Remote Nodes (MQTT) ── Master Node (MQTT) ──┬── Dashboard
                                                   └── HTTP Server ── Remote Monitor (HTTP/cellular)
```

---

## Configuration Examples

See `config/transport_examples.json` for complete examples of:
- MQTT (local and authenticated)
- LoRa (US, EU, Asia, long-range)
- HTTP (local and cloud)
- Serial (Linux and Windows)

**Quick config**:
```python
from common.transport import create_transport

# MQTT
transport = create_transport('mqtt', broker='192.168.1.100')

# LoRa
transport = create_transport('lora', frequency=915, node_id=1)

# HTTP
transport = create_transport('http', base_url='http://192.168.1.100:8080', node_id='remote-1')

# Serial
transport = create_transport('serial', port='/dev/ttyUSB0', node_id=1)
```

---

## Implementation Notes

### All transports support:
- ✅ Topic-based messaging (pub/sub pattern)
- ✅ Wildcard subscriptions (`+` for single level, `#` for multi-level)
- ✅ JSON data serialization
- ✅ Connection management (auto-reconnect)
- ✅ Statistics tracking

### Transport-specific features:
- **MQTT**: QoS levels (0, 1, 2), retained messages, authentication
- **LoRa**: RSSI/SNR tracking, adaptive data rate, sequence numbering
- **HTTP**: Authentication tokens, polling interval tuning
- **Serial**: Frame-based protocol (STX/ETX), error detection

---

## Bandwidth Requirements

Bass Sentry needs **16 kb/s per node** (at 1 kHz sampling):

| Transport | Bandwidth | Sufficient? |
|-----------|-----------|-------------|
| MQTT (WiFi) | 1-100 Mb/s | ✅ Yes (6000x more than needed) |
| LoRa (SF7) | 0.3-50 kb/s | ✅ Yes (tight but sufficient) |
| HTTP (cellular) | 1-100 Mb/s | ✅ Yes (6000x more than needed) |
| Serial (115200 baud) | 115 kb/s | ✅ Yes (7x more than needed) |

**All transports work for bass monitoring!**

---

## Troubleshooting

### MQTT
- **Cannot connect**: Check broker is running (`systemctl status mosquitto`)
- **Timeout**: Verify firewall allows port 1883
- **Authentication failed**: Check username/password
- **Poor range**: Add WiFi extenders or switch to LoRa

### LoRa
- **No connection**: Verify frequency matches region (915 US, 868 EU, 433 Asia)
- **Short range**: Increase spreading factor (SF7 → SF12)
- **Intermittent**: Check antenna connection, elevate antenna
- **Module not found**: Install library (`pip install adafruit-circuitpython-rfm9x`)

### HTTP
- **Cannot connect**: Verify server is running, check firewall
- **High latency**: Reduce poll interval (but don't go below 0.1s)
- **401 Unauthorized**: Check auth token
- **Data costs**: Reduce poll interval or use local transport

### Serial
- **Port not found**: Check port name (`ls /dev/ttyUSB*` or Device Manager)
- **Permission denied**: Add user to dialout group (`sudo usermod -a -G dialout $USER`)
- **Garbled data**: Verify baudrate matches on both ends
- **No data**: Check cable, try different USB port

---

## Next Steps

1. Choose transport based on venue requirements
2. Copy relevant config from `config/transport_examples.json`
3. Install any required hardware (LoRa HAT, USB adapter, etc.)
4. Test connection before deployment
5. Monitor statistics during operation

For integration into existing code, see:
- `common/transport.py` - Abstract transport interface
- `common/transport_mqtt.py` - MQTT implementation
- `common/transport_lora.py` - LoRa implementation
- `common/transport_http.py` - HTTP implementation
- `common/transport_serial.py` - Serial implementation
