# Bass Sentry Test Fleet

Test the entire Bass Sentry deployment locally using Docker, without real Raspberry Pi hardware.

## What This Does

Creates a simulated deployment with:
- **Master node** - InfluxDB, Grafana, MQTT, Graylog
- **4 fake Pi nodes** - Generate synthetic audio data
  - `stage` (reference node)
  - `dance_floor` (remote)
  - `back_bar` (remote)
  - `neighbor` (remote)

The fake nodes:
- Have simulated Pi serial numbers
- Send synthetic audio data (sine waves + noise)
- Send dB level measurements
- Log to both local stdout and Graylog
- Support cross-correlation (with synthetic signals)

## Quick Start

```bash
# From repository root
cd /path/to/bass-sentry

# Build and start the fleet
docker compose -f docker-compose.test-fleet.yml up --build

# In another terminal, verify it's working (wait ~30 seconds first)
./deployment/test-fleet/verify-fleet.sh
```

## Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3001 | admin / grafanapass |
| InfluxDB | http://localhost:8086 | admin / supersecret |
| Graylog | http://localhost:9001 | admin / graylog-password |
| MQTT | localhost:1883 | (no auth) |

## View Logs

```bash
# All services
docker compose -f docker-compose.test-fleet.yml logs -f

# Specific node
docker compose -f docker-compose.test-fleet.yml logs -f fake-pi-stage
docker compose -f docker-compose.test-fleet.yml logs -f fake-pi-dance-floor

# Master node
docker compose -f docker-compose.test-fleet.yml logs -f master-node
```

## Graylog Setup (First Time)

After Graylog starts (may take 1-2 minutes):

1. Go to http://localhost:9001
2. Login: admin / graylog-password
3. Go to **System > Inputs**
4. Select **GELF UDP** from dropdown
5. Click **Launch new input**
6. Title: "Bass Sentry Nodes", Port: 12201
7. Click **Save**

Now you'll see logs from all fake nodes in Graylog.

## What to Verify

### In Grafana

1. Open the **Overview** dashboard
2. You should see dB level readings from all 4 nodes
3. The traffic light gauges should be active

### In InfluxDB

1. Go to Data Explorer
2. Query: `from(bucket: "mybucket") |> range(start: -5m)`
3. You should see:
   - `dBSPL` measurements from each node
   - `node_health` heartbeats
   - `cross_correlation` data (after a few minutes)

### In Graylog

1. Go to Search
2. You should see log messages from all nodes
3. Filter by `facility:bass-sentry-*` for Bass Sentry only

## Customization

### Add More Nodes

Copy a node definition in `docker-compose.test-fleet.yml`:

```yaml
fake-pi-new-location:
  build:
    context: .
    dockerfile: deployment/test-fleet/Dockerfile.fake-pi
  environment:
    PI_SERIAL: "NEWLOC01"
    NODE_NAME: "new_location"
    MQTT_HOST: "mosquitto"
    GRAYLOG_HOST: "graylog"
    USE_FAKE_AUDIO: "true"
    IS_REFERENCE: "false"
  depends_on:
    - mosquitto
    - master-node
  networks:
    - bass-sentry-net
```

### Simulate Different Audio

Edit `deployment/test-fleet/entrypoint.sh` and modify the `generate_fake_audio()` function to create different signal patterns.

## Cleanup

```bash
# Stop and remove containers
docker compose -f docker-compose.test-fleet.yml down

# Also remove volumes (deletes all data)
docker compose -f docker-compose.test-fleet.yml down -v
```

## Limitations

- **No real audio** - Uses synthetic data, can't test actual microphone capture
- **No real cross-correlation** - Synthetic signals don't have realistic delays
- **No real Pi hardware** - Can't test GPIO, I2S mics, etc.
- **Network is local** - Can't test mDNS discovery across networks

## Troubleshooting

### Nodes not sending data

```bash
# Check node logs
docker compose -f docker-compose.test-fleet.yml logs fake-pi-stage

# Check if MQTT is receiving
docker compose -f docker-compose.test-fleet.yml exec mosquitto mosquitto_sub -t '#' -v
```

### Graylog not receiving logs

1. Ensure GELF UDP input is created (see setup above)
2. Check Graylog is fully started (can take 1-2 min)
3. Check node has GRAYLOG_HOST set correctly

### InfluxDB has no data

```bash
# Check master node is processing
docker compose -f docker-compose.test-fleet.yml logs master-node

# Verify MQTT connection
docker compose -f docker-compose.test-fleet.yml logs mosquitto
```
