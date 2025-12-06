# LoRa Quick Start Guide

**Perfect for venues with WiFi issues, outdoor festivals, or large spaces.**

---

## Why LoRa?

✅ **No WiFi needed** - Works on dedicated radio frequency
✅ **Long range** - 2-10 km (vs WiFi's 50-100m)
✅ **Better penetration** - Goes through concrete/metal walls
✅ **No interference** - Won't conflict with phones/laptops
✅ **Reliable** - Dedicated channel, no network congestion

---

## Shopping List

### Required Hardware

**Per Raspberry Pi** (remote nodes + master):
- **Dragino LoRa/GPS HAT** - $25
  - Model: "915 MHz" for US/Canada
  - Model: "868 MHz" for Europe
  - Model: "433 MHz" for Asia
  - Includes antenna (critical!)

**Where to buy**:
- Amazon: Search "Dragino LoRa HAT 915MHz Raspberry Pi"
- Adafruit: RFM95W LoRa Radio ($20) + breakout board
- RAK Wireless: RAK811 LoRa Module ($20-40)

**Recommended**: Dragino LoRa/GPS HAT (easiest to install)

---

## Installation Steps

### 1. Enable SPI on Raspberry Pi

```bash
sudo raspi-config
# Navigate to: Interface Options → SPI → Enable
sudo reboot
```

### 2. Install LoRa Library

```bash
pip install adafruit-circuitpython-rfm9x
```

### 3. Attach Hardware

1. **Power off Raspberry Pi** (`sudo shutdown -h now`)
2. **Attach LoRa HAT** to 40-pin GPIO header (sits on top of Pi)
3. **Screw on antenna** (the included whip antenna)
4. **Power on Pi**

⚠️ **CRITICAL**: Always attach antenna before powering on! Transmitting without antenna damages the radio.

### 4. Configure Bass Sentry

**Option A: Use recommended config**
```bash
cp config/lora_recommended.json config/transport.json
```

**Option B: Add to existing config**
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

**Important**: Change `node_id` for each node:
- Master node: `node_id: 0`
- Remote node 1: `node_id: 1`
- Remote node 2: `node_id: 2`
- etc.

### 5. Test Connection

**On remote node**:
```python
from common.transport import create_transport

transport = create_transport('lora', frequency=915, node_id=1, gateway_id=0)
transport.connect()

# Send test message
transport.send('test/remote-1', {'status': 'hello from remote 1'})
```

**On master node**:
```python
from common.transport import create_transport

def on_message(topic, data):
    print(f"Received: {topic} -> {data}")

transport = create_transport('lora', frequency=915, node_id=0)
transport.connect()
transport.subscribe('test/#', on_message)

# Keep running
import time
while True:
    time.sleep(1)
```

You should see "Received: test/remote-1 -> {'status': 'hello from remote 1'}"

---

## Frequency Selection

**Critical**: Use the correct frequency for your region!

| Region | Frequency | Model to Buy |
|--------|-----------|--------------|
| **US/Canada/South America** | 915 MHz | Dragino LoRa HAT 915MHz |
| **Europe** | 868 MHz | Dragino LoRa HAT 868MHz |
| **Asia** | 433 MHz | Dragino LoRa HAT 433MHz |

**In config**: Set `"frequency": 915` (or 868, or 433)

---

## Range Configuration

Bass Sentry works with **all spreading factors** (still fast enough for 16 kb/s per node).

### Balanced (Recommended)
```json
{
  "spreading_factor": 7,
  "tx_power": 20
}
```
- **Range**: 2-5 km outdoor, 500m-1km indoor
- **Speed**: Fast (perfect for bass monitoring)
- **Best for**: Most venues

### Maximum Range
```json
{
  "spreading_factor": 12,
  "tx_power": 23
}
```
- **Range**: 5-20 km outdoor, 1-2 km indoor
- **Speed**: Slower, but still sufficient for bass (16 kb/s requirement)
- **Best for**: Large outdoor festivals, multiple buildings

### Short Range / Indoor
```json
{
  "spreading_factor": 7,
  "tx_power": 13
}
```
- **Range**: 500m-1km outdoor, 200-500m indoor
- **Speed**: Fastest
- **Best for**: Indoor venues with good line of sight

**Rule of thumb**:
- Start with **SF7, 20 dBm** (balanced)
- If range is too short → increase to **SF10** or **SF12**
- If updates are slow → decrease to **SF7**

---

## Antenna Placement

For best performance:

✅ **Mount vertically** - Antenna should point straight up
✅ **Elevate** - Higher is better (roof, pole, etc.)
✅ **Line of sight** - Clear view between nodes if possible
✅ **Away from metal** - Keep antenna away from metal objects

**Range improvements**:
- Ground level: 1 km
- 3m elevation: 2-3 km
- 10m elevation (roof): 5-10 km

---

## Typical Ranges

### Indoor Venue
- **SF7**: 500m-1km
- **SF10**: 1-2 km
- **SF12**: 1-2 km (not much improvement indoors)

### Outdoor Festival
- **SF7**: 2-5 km
- **SF10**: 5-10 km
- **SF12**: 10-20 km

### Urban (buildings, obstacles)
- **SF7**: 1-2 km
- **SF10**: 2-5 km
- **SF12**: 5-10 km

**Note**: LoRa penetrates concrete/metal better than WiFi!

---

## Troubleshooting

### No Connection

**Check frequency**:
```python
# config.json
"frequency": 915  # US/Canada
"frequency": 868  # Europe
"frequency": 433  # Asia
```

**Check antenna**: Make sure antenna is screwed on tightly

**Check node IDs**: Each node needs unique `node_id` (0, 1, 2, ...)

**Check SPI enabled**:
```bash
ls /dev/spidev*
# Should show: /dev/spidev0.0  /dev/spidev0.1
```

### Short Range

**Increase spreading factor**:
```json
"spreading_factor": 10  // or 12
```

**Increase transmit power**:
```json
"tx_power": 23  // maximum
```

**Elevate antenna**: Move to higher location (roof, pole)

**Check line of sight**: Remove obstacles between nodes

### Slow Updates

**Decrease spreading factor**:
```json
"spreading_factor": 7  // fastest
```

**Note**: Even SF12 is fast enough for bass monitoring!

### Intermittent Connection

**Check RSSI/SNR**:
```python
stats = transport.get_stats()
print(f"Signal strength: {stats['rssi_last']} dBm")
print(f"SNR: {stats['snr_last']} dB")
```

**Good signal**: RSSI > -120 dBm, SNR > 0 dB
**Weak signal**: Increase SF or TX power, elevate antenna

---

## Testing Range

Before deploying, test your range:

1. **Place remote node at furthest location** (neighbor's house, edge of venue)
2. **Start remote node** with LoRa transport
3. **Monitor on master node**:
   ```python
   transport.get_stats()
   # Check: rssi_last, snr_last, messages_received
   ```
4. **If weak signal**: Increase SF or TX power, elevate antenna

**RSSI guide**:
- `-70 dBm`: Excellent
- `-90 dBm`: Good
- `-110 dBm`: Fair (usable)
- `-120 dBm`: Weak (increase SF/power)
- `-130 dBm`: Very weak (may drop)

---

## Cost Breakdown

| Item | Cost | Quantity | Total |
|------|------|----------|-------|
| Dragino LoRa HAT (915 MHz) | $25 | 1 per Pi | $25/node |
| Antenna | Included | - | $0 |
| **Total per node** | - | - | **$25** |

**Example 5-node system**:
- 1 master + 4 remotes = 5 HATs
- Total: $125

**Comparison to WiFi extenders**:
- WiFi mesh system (5 nodes): $200-400
- LoRa (5 nodes): $125
- **LoRa is cheaper and more reliable!**

---

## Advanced: Multiple Gateways

For very large venues, you can use multiple LoRa gateways:

```
Remote Nodes (LoRa)
   ↓
Gateway 1 (LoRa → Ethernet) ──┐
                               ├→ Master Node
Gateway 2 (LoRa → Ethernet) ──┘
```

Each gateway can handle ~100 nodes, giving you 200+ node capacity.

---

## Summary

✅ **Hardware**: Dragino LoRa HAT ($25 per node)
✅ **Frequency**: 915 MHz (US), 868 MHz (EU), 433 MHz (Asia)
✅ **Config**: `spreading_factor: 7`, `tx_power: 20` (balanced)
✅ **Range**: 2-5 km outdoor, 500m-1km indoor
✅ **Antenna**: Mount vertically, elevate for best range

**LoRa solves WiFi issues and gives you 20x the range!**

---

## Next Steps

1. **Order hardware**: Dragino LoRa HAT (915 MHz for US)
2. **Install on all Pis**: Master + remote nodes
3. **Copy config**: `cp config/lora_recommended.json config/transport.json`
4. **Test range**: Deploy remote node at furthest location
5. **Deploy**: No more WiFi issues!

For detailed documentation, see `docs/TRANSPORTS.md`.
