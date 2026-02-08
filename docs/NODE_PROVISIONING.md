# Node Provisioning Guide

This guide explains how to set up and deploy Bass Sentry monitoring nodes (Raspberry Pis) at scale.

## Overview

Each node identifies itself by its **Pi serial number**, which is printed on a sticker on every Raspberry Pi board. This enables a simple workflow:

1. Read serial from Pi sticker
2. Map serial to friendly name in config
3. Label the enclosure
4. Flash a generic SD card
5. Deploy

No per-device SD card customization required.

---

## Quick Start

### Step 1: Gather Your Pis

For each Raspberry Pi:

1. Look at the board sticker (usually near the GPIO pins or on the bottom)
2. Find the serial number: `10000000XXXXXXXX`
3. Note the **last 8 characters** (e.g., `ABCD1234`)

### Step 2: Create Name Mappings

Edit `config/node_names.json` on your master node:

```json
{
    "mappings": {
        "ABCD1234": {
            "name": "dance_cave",
            "label": "Dance Cave",
            "type": "remote"
        },
        "EFGH5678": {
            "name": "stage",
            "label": "Stage (Reference)",
            "type": "reference"
        },
        "IJKL9012": {
            "name": "neighbor_north",
            "label": "Neighbor (North)",
            "type": "remote"
        }
    }
}
```

### Step 3: Label Your Enclosures

Print labels with the friendly names and stick them on the Pi enclosures:
- "DANCE CAVE"
- "STAGE"
- "NEIGHBOR NORTH"

### Step 4: Flash SD Cards

All SD cards use the **same generic image**:

1. Download Raspberry Pi OS Lite (64-bit)
2. Flash with Raspberry Pi Imager
3. Copy cloud-init files to boot partition:
   - `deployment/cloud-init/user-data` → boot partition as `user-data`
   - `deployment/cloud-init/network-config` → boot partition as `network-config`

**Important:** Edit `network-config` with your WiFi credentials before copying.

### Step 5: Deploy

1. Insert SD card into labeled Pi
2. Power on
3. Wait ~3 minutes for first boot setup
4. Node appears in dashboard with its friendly name

---

## How Node Identity Works

The node determines its identity using this priority:

| Priority | Source | Example | Use Case |
|----------|--------|---------|----------|
| 1 | `NODE_NAME` env var | `dance_cave` | Explicit override |
| 2 | Custom hostname | `bass-dance-cave` | If you customized hostname |
| 3 | Pi serial number | `ABCD1234` | Default for Pis |
| 4 | MAC address | `b8:27:eb:aa:bb:cc` | Non-Pi systems |

The serial number is then mapped to a friendly name via `config/node_names.json`.

---

## Finding the Serial Number

### On the Board Sticker

Every Raspberry Pi has a sticker with its serial number:
- **Pi 4/5**: Bottom of board or near USB ports
- **Pi 3**: Near GPIO header or on bottom
- **Pi Zero**: On bottom of board

The format is: `10000000XXXXXXXX`

Use the last 8 characters (`XXXXXXXX`).

### Via Command Line

If the Pi is already running:

```bash
cat /proc/cpuinfo | grep Serial
# Output: Serial          : 10000000abcd1234
#                                   ^^^^^^^^
#                                   Use these
```

Or the shorter version:
```bash
cat /proc/cpuinfo | grep Serial | cut -d: -f2 | tail -c 9
# Output: ABCD1234
```

---

## Cloud-Init Configuration

### Before First Use: Customize These Files

You MUST edit these files before flashing your first SD card:

#### 1. Edit `deployment/cloud-init/user-data`

```yaml
# Line ~43: Add your SSH public key
ssh_authorized_keys:
  - ssh-rsa AAAA_YOUR_ACTUAL_KEY_HERE you@yourcomputer

# Line ~77: Change to your repo URL (or keep if using main repo)
git clone https://github.com/YOUR_USERNAME/bass-sentry.git
```

#### 2. Edit `deployment/cloud-init/network-config`

```yaml
wifis:
  wlan0:
    dhcp4: true
    access-points:
      "YourWiFiNetwork":        # Your actual SSID
        password: "YourPassword" # Your actual password
```

### What Cloud-Init Does

On first boot, the Pi will automatically:

1. Create `bass` user (password: `bass` - change it!)
2. Install system packages (git, python3, portaudio, etc.)
3. Clone the Bass Sentry repository
4. Create Python virtual environment
5. Install Python dependencies
6. Configure and start the systemd service
7. Enable mDNS/Avahi for network discovery
8. Set up helpful command aliases

### SSH Access

After first boot (wait 3-5 minutes):

```bash
# Via mDNS (if on same network)
ssh bass@bass-node.local

# Or via IP (find it on your router)
ssh bass@192.168.1.xxx

# Default password: bass
# CHANGE IT: passwd
```

### Helpful Commands (After SSH)

These aliases are set up automatically:

```bash
logs      # View live service logs
status    # Check service status
restart   # Restart the service
stop      # Stop the service
start     # Start the service
errors    # View only error logs
serial    # Show Pi serial number
```

Or use the full commands:
```bash
journalctl -u bass_sentry_node -f          # Live logs
journalctl -u bass_sentry_node --since "1 hour ago"  # Recent logs
sudo systemctl status bass_sentry_node     # Status
```

### Customizing the Master Node Address

By default, nodes look for `bass-master.local` via mDNS. To change this, edit the systemd service section in `user-data`:

```yaml
Environment="MQTT_HOST=192.168.1.100"  # Use IP if mDNS unreliable
```

---

## Deployment at Scale

### Batch Flashing

For many nodes, use a multi-SD card writer or script:

```bash
# Example using dd (adjust device names!)
for device in /dev/sd{b,c,d,e}; do
    sudo dd if=raspios.img of=$device bs=4M status=progress &
done
wait

# Then copy cloud-init to each
for mount in /media/user/boot*; do
    cp deployment/cloud-init/user-data "$mount/"
    cp deployment/cloud-init/network-config "$mount/"
done
```

### Using Ansible for Updates

Once nodes are deployed, use Ansible for updates:

```bash
# Update all nodes
ansible-playbook -i deployment/ansible/inventory.yml deployment/ansible/playbook.yml --tags update

# Update specific node
ansible-playbook -i deployment/ansible/inventory.yml deployment/ansible/playbook.yml --limit dance-cave
```

---

## Troubleshooting

### Node Not Appearing in Dashboard

1. **Check WiFi connection**: SSH to Pi, run `ping bass-master.local`
2. **Check service status**: `sudo systemctl status bass_sentry_node`
3. **Check logs**: `journalctl -u bass_sentry_node -f`
4. **Verify serial mapping**: Ensure serial in config matches Pi

### Finding a Node's Serial After Deployment

If you forgot to note the serial:

```bash
# SSH to the Pi
ssh bass@bass-node.local

# Get serial
cat /proc/cpuinfo | grep Serial
```

### Node Shows Serial Instead of Friendly Name

The serial→name mapping isn't loaded. Check:
1. `config/node_names.json` exists on master
2. Serial is correct (case-insensitive, but use uppercase)
3. Restart the web dashboard if running

### Multiple Nodes with Same Name

Each serial must map to a unique name. If you see duplicates:
1. Check for typos in serial numbers
2. Verify each Pi has its correct SD card

---

## Reference Node Setup

The reference node (at the stage/sound source) needs one additional configuration to tag its audio as "reference" for cross-correlation:

In the DAG file, ensure the reference node has:
```json
{
    "tags": ["reference"]
}
```

Or set the environment variable:
```bash
Environment="NODE_TYPE=reference"
```

---

## Hardware Recommendations

### Raspberry Pi Model

- **Recommended**: Pi 4 (2GB+) or Pi 5
- **Works**: Pi 3B+, Pi Zero 2 W
- **Not recommended**: Pi Zero (original), Pi 2

### Microphone

- USB audio interface + calibrated measurement mic (best accuracy)
- USB microphone (convenient, less accurate)
- I2S MEMS microphone (compact, requires soldering)

### Enclosure

- Weatherproof if outdoor
- Label clearly with node name
- Include serial number on label for reference

---

## Centralized Logging with Graylog

For easier debugging across many nodes, you can send all logs to a central Graylog server.

### 1. Enable Graylog on Master

The docker-compose.yml includes Graylog (with MongoDB and OpenSearch). It starts automatically with `docker compose up`.

**Access Graylog UI:** http://localhost:9000
**Login:** admin / graylog-password

### 2. Create GELF Input (One-time Setup)

After Graylog starts:
1. Go to **System > Inputs**
2. Select **GELF UDP** from dropdown
3. Click **Launch new input**
4. Title: "Bass Sentry Nodes"
5. Port: 12201
6. Click **Save**

### 3. Enable on Remote Nodes

Edit the systemd service on each node (or update cloud-init before deployment):

```bash
# SSH to node
ssh bass@bass-node.local

# Edit the service
sudo systemctl edit bass_sentry_node

# Add these lines:
[Service]
Environment="GRAYLOG_HOST=bass-master.local"
Environment="GRAYLOG_PORT=12201"

# Restart
sudo systemctl restart bass_sentry_node
```

Or with Ansible:
```bash
ansible all -i inventory.yml -m systemd -a "name=bass_sentry_node state=restarted" \
  -e "GRAYLOG_HOST=bass-master.local"
```

### 4. View Logs

In Graylog UI:
- **Search > All messages** - see all node logs
- Filter by `facility:bass-sentry-*` to see only Bass Sentry
- Filter by `facility:bass-sentry-dance_cave` for specific node
- Create dashboards for error rates, node activity, etc.

### Local Logs (Always Available)

Even without Graylog, logs are always available locally via journald:

```bash
# SSH to any node
ssh bass@bass-node.local

# View logs
logs              # alias for live logs
errors            # alias for error-only logs
journalctl -u bass_sentry_node --since "1 hour ago"
```

---

## Testing Without Hardware

You can test the entire deployment locally using Docker:

```bash
# Build and start simulated fleet (1 master + 4 fake Pis)
docker compose -f docker-compose.test-fleet.yml up --build

# Verify everything is working
./deployment/test-fleet/verify-fleet.sh
```

This creates fake Pi nodes that send synthetic audio data, allowing you to:
- Test Grafana dashboards
- Test Graylog log aggregation
- Test master node processing
- Verify the deployment pipeline

See `deployment/test-fleet/README.md` for details.

---

## Summary Checklist

- [ ] Note serial numbers from all Pi boards
- [ ] Add mappings to `config/node_names.json`
- [ ] Edit `network-config` with WiFi credentials
- [ ] Flash SD cards with Raspberry Pi OS Lite
- [ ] Copy cloud-init files to boot partitions
- [ ] Label enclosures with friendly names
- [ ] Deploy nodes to locations
- [ ] Verify nodes appear in dashboard
