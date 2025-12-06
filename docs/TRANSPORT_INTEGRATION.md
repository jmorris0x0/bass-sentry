# Transport Integration Guide

**How to use pluggable transports with Bass Sentry**

---

## Quick Start

### Current System (MQTT/WiFi) - No Changes Needed

**Your existing setup still works!** No configuration changes required.

The system automatically uses MQTT with service discovery (Avahi) if no transport configuration is provided.

```bash
# This still works exactly as before
./remote-node/remote_node.py config.json
```

---

## Using LoRa (or Other Transports)

### Remote Node Configuration

**Add `transport` section to your existing config file:**

```json
{
  "location": "dance-floor",

  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "node_id": 1,
      "gateway_id": 0
    }
  },

  "steps": {
    ...existing DAG configuration...
  }
}
```

**Then run normally:**
```bash
./remote-node/remote_node.py config.json
```

The system will automatically use LoRa instead of MQTT!

### Master Node Configuration

**Option 1: Environment Variable**

```bash
export BASS_SENTRY_TRANSPORT_CONFIG=/path/to/transport-config.json
docker-compose up
```

Where `transport-config.json` contains:
```json
{
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "node_id": 0
    }
  }
}
```

**Option 2: No Configuration (Use Default MQTT)**

```bash
# No environment variable = use legacy MQTT (backward compatible)
docker-compose up
```

---

## Transport Options

### 1. MQTT (WiFi) - Default

**No configuration needed!** Service discovery (Avahi) finds master node automatically.

**Or explicitly configure:**
```json
{
  "transport": {
    "type": "mqtt",
    "mqtt": {
      "broker": "192.168.1.100",
      "port": 1883,
      "qos": 1
    }
  }
}
```

### 2. LoRa (Long Range) - Recommended for WiFi Issues

```json
{
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "tx_power": 20,
      "spreading_factor": 7,
      "node_id": 1,
      "gateway_id": 0
    }
  }
}
```

**Hardware required**: Dragino LoRa HAT ($25)

**Range**: 2-10 km outdoor, 500m-1km indoor

**See**: `docs/LORA_QUICKSTART.md` for complete setup guide

### 3. HTTP (Cellular/Internet)

```json
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

**Hardware required**: None (uses built-in networking)

**Range**: Unlimited (anywhere with internet)

### 4. Serial (Wired)

```json
{
  "transport": {
    "type": "serial",
    "serial": {
      "port": "/dev/ttyUSB0",
      "baudrate": 115200,
      "node_id": 1
    }
  }
}
```

**Hardware required**: USB cable

**Range**: 5-15m

---

## Example Configurations

### Example 1: WiFi System (Current - No Changes)

**Remote nodes**: No transport config → uses MQTT with service discovery
**Master node**: No transport config → uses MQTT broker

```bash
# Remote node
./remote-node/remote_node.py config/remote-node-default.json

# Master node
docker-compose up
```

### Example 2: LoRa System (WiFi Issues Solved!)

**Remote nodes**: Add LoRa transport config
```json
{
  "location": "dance-floor",
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "node_id": 1,  // Change for each node: 1, 2, 3, ...
      "gateway_id": 0
    }
  },
  "steps": {...}
}
```

**Master node**: Create transport config file
```json
{
  "transport": {
    "type": "lora",
    "lora": {
      "frequency": 915,
      "node_id": 0  // Master is gateway (0)
    }
  }
}
```

**Run:**
```bash
# Remote nodes
./remote-node/remote_node.py config/remote-node-lora.json

# Master node
export BASS_SENTRY_TRANSPORT_CONFIG=/path/to/lora-master-config.json
docker-compose up
```

### Example 3: Mixed Transports

**You can use different transports for different parts of the system!**

**Remote nodes**: LoRa (long range)
**Master node**: LoRa receiver → MQTT → Grafana

This is the recommended setup for venues with WiFi issues.

---

## Node ID Assignment

### MQTT
- Node IDs automatically assigned (MAC address)
- No manual configuration needed

### LoRa/HTTP/Serial
- **Master/Gateway**: `node_id: 0`
- **Remote node 1**: `node_id: 1`
- **Remote node 2**: `node_id: 2`
- **Remote node 3**: `node_id: 3`
- etc.

**Important**: Each node must have a unique ID!

---

## Frequency Selection (LoRa)

| Region | Frequency |
|--------|-----------|
| US/Canada/South America | 915 MHz |
| Europe | 868 MHz |
| Asia | 433 MHz |

**Set in config:**
```json
"frequency": 915  // or 868, or 433
```

---

## Troubleshooting

### Remote Node Not Connecting

**Check logs:**
```bash
# Should see: "Using pluggable transport: lora" (or other transport)
# If you see: "Using legacy MQTT with service discovery" - transport config not loaded
```

**Fix**: Verify transport config is in the JSON file under `"transport"` key

### Master Node Not Receiving

**MQTT (legacy)**:
- Check Mosquitto is running: `docker-compose logs mosquitto`
- Check service discovery: `avahi-browse -a`

**LoRa**:
- Check frequency matches: Master and remotes must use same frequency
- Check node IDs: Master should be 0, remotes should be 1, 2, 3, ...
- Check antenna: Must be attached before powering on

**HTTP**:
- Check server is running
- Check URL is correct
- Check firewall allows traffic

### "Transport not available" Error

**Missing library!** Install required transport library:

```bash
# LoRa
pip install adafruit-circuitpython-rfm9x

# Serial
pip install pyserial

# HTTP (built-in, no install needed)
pip install requests
```

---

## Migration Path

### Current System → LoRa

1. **Order hardware**: Dragino LoRa HAT ($25 per node)
2. **Install on Pis**: Attach HAT, install library
3. **Update configs**: Add `transport` section to config files
4. **Test one node**: Verify LoRa works before deploying all nodes
5. **Deploy**: Replace all nodes' configs, restart

**No code changes needed!** Just config file updates.

---

## Performance

All transports support Bass Sentry's bandwidth requirements (16 kb/s per node):

| Transport | Bandwidth | Latency | Reliability |
|-----------|-----------|---------|-------------|
| MQTT (WiFi) | 1-100 Mb/s | <100ms | Good (if WiFi is good) |
| LoRa | 0.3-50 kb/s | <500ms | Excellent (dedicated channel) |
| HTTP | 1-100 Mb/s | 100-500ms | Good (if internet is good) |
| Serial | 9.6-115 kb/s | <10ms | Excellent (wired) |

---

## Complete Documentation

- **Transport Guide**: `docs/TRANSPORTS.md` - Complete comparison of all transports
- **LoRa Quick Start**: `docs/LORA_QUICKSTART.md` - Hardware setup and configuration
- **Config Examples**: `config/transport_examples.json` - All transport configurations

---

## Summary

✅ **Backward compatible** - Existing MQTT systems work without changes
✅ **Drop-in replacement** - Just add `transport` section to config
✅ **No code changes** - Pure configuration
✅ **Solves WiFi issues** - LoRa provides 2-10km range, better penetration
✅ **Easy migration** - Update configs, install hardware, restart

**Need help?** See `docs/TRANSPORTS.md` or `docs/LORA_QUICKSTART.md`
