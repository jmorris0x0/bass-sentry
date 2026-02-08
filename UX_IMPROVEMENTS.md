# Bass Sentry - UX Improvements

This document outlines UX issues identified during review and proposed improvements.

---

## Status Summary

| Section | Item | Status |
|---------|------|--------|
| 1.1 | Fix distances dashboard provisioning | ✅ Done |
| 1.2 | Add template variables for locations | ✅ Done |
| 1.3 | Add node health panel | ✅ Done |
| 2.1 | Cross-correlation waveform visualization | ✅ Done |
| 2.2 | Venue map dashboard | ✅ Done (custom web dashboard) |
| 2.3 | Distance radar visualization | ✅ Done (custom web dashboard) |
| 3.1 | Pre-built Pi image with cloud-init | ✅ Done |
| 3.2 | Ansible playbook for fleet deployment | ✅ Done |
| 3.3 | Calibration workflow | ✅ Done |
| 4.1 | Event manager dashboard | ⏳ Future |
| 4.2 | Alerting configuration | ✅ Done |
| 4.3 | Mobile-optimized view | ⏳ Future (web dashboard is responsive) |

**Completed:**
- Moved distances dashboard to auto-provisioning folder
- Fixed bucket name in distances dashboard (was `bass_sentry`, now `mybucket`)
- Added template variables for location/band to overview dashboard
- Added heartbeat writing to InfluxDB in node_manager.py
- Created node_health.json dashboard with status table, message stats, buffer monitoring
- Added correlation waveform PNG generation (matplotlib) with auto-save
- Created Flask web server (`web/server.py`) for custom dashboard
- Created custom web dashboard with distance radar, waveform display, node health
- Created Ansible playbook for fleet deployment (`deployment/ansible/`)
- Created cloud-init config for Raspberry Pi provisioning (`deployment/cloud-init/`)
- Created calibration script (`tools/calibrate.py`)
- Added Grafana alerting rules (`grafana-provisioning/alerting/`)
- Added node name mapping config (`config/node_names.json`)

---

## 1. Dashboard Fixes (Quick Wins)

### 1.1 Fix Distances Dashboard Provisioning

**Problem:** `grafana/dashboards/bass-sentry-distances.json` exists but isn't in the provisioning folder, so it doesn't auto-load.

**Fix:** Move to correct location.

```bash
mv grafana/dashboards/bass-sentry-distances.json \
   grafana-provisioning/dashboards/bass-sentry-distances.json
```

**Time:** 2 minutes

---

### 1.2 Add Template Variables for Locations

**Problem:** Location names hardcoded ("Dance_Cave", "Mainspace", "32_Langton"). Dashboards not reusable for different events.

**Fix:** Add Grafana template variables that query available locations from InfluxDB.

```json
{
  "templating": {
    "list": [
      {
        "name": "location",
        "type": "query",
        "query": "import \"influxdata/influxdb/schema\"\nschema.tagValues(bucket: \"mybucket\", tag: \"location\")",
        "datasource": "InfluxDB",
        "multi": true,
        "includeAll": true
      }
    ]
  }
}
```

Then update queries to use `${location}` instead of hardcoded values:
```flux
filter(fn: (r) => r["location"] =~ /${location:regex}/)
```

**Time:** 1 hour

---

### 1.3 Add Node Health Panel

**Problem:** No visibility into whether remote nodes are connected and sending data.

**Fix:** Create a panel showing:
- Last seen timestamp per node
- Connection status (green/yellow/red based on time since last heartbeat)
- Message statistics (sent/failed/buffered)

**Dashboard Panel:**
```json
{
  "title": "Node Health",
  "type": "table",
  "targets": [
    {
      "query": "from(bucket: \"mybucket\")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r[\"_measurement\"] == \"heartbeat\")\n  |> last()\n  |> pivot(rowKey:[\"node_name\"], columnKey: [\"_field\"], valueColumn: \"_value\")"
    }
  ],
  "fieldConfig": {
    "overrides": [
      {
        "matcher": {"id": "byName", "options": "status"},
        "properties": [
          {
            "id": "mappings",
            "value": [
              {"type": "value", "options": {"connected": {"color": "green", "text": "●"}}},
              {"type": "value", "options": {"disconnected": {"color": "red", "text": "●"}}}
            ]
          }
        ]
      }
    ]
  }
}
```

**Requires:** Heartbeat data to be written to InfluxDB (currently only tracked in memory in `node_manager.py`).

**Time:** 2 hours

---

## 2. Impressive Visualizations (The Cool Stuff)

### 2.1 Cross-Correlation Waveform Visualization

**Problem:** The cross-correlation analysis is the coolest part of the system, but it's invisible to users. The correlation waveform with its peak showing the detected delay would be visually stunning proof that the system works.

**Options:**

**Option A: Pre-rendered Image (Easier)**
- Modify `correlation.py` to save correlation plot as PNG
- Serve via simple HTTP endpoint
- Display in Grafana using Image panel

```python
# In correlation.py, after computing correlation
def save_correlation_plot(self, correlation, lags, remote_id, detected_lag):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(lags / self.sample_rate * 1000, correlation, 'b-', linewidth=0.5)
    ax.axvline(x=detected_lag / self.sample_rate * 1000, color='r', linestyle='--',
               label=f'Detected: {detected_lag/self.sample_rate*1000:.1f}ms')
    ax.set_xlabel('Lag (ms)')
    ax.set_ylabel('Correlation')
    ax.set_title(f'Cross-Correlation: {remote_id}')
    ax.legend()

    plt.savefig(f'/var/www/correlation/{remote_id}.png', dpi=100)
    plt.close()
```

**Option B: Real-time Chart (Harder)**
- Store correlation data points in InfluxDB
- Query and display in Grafana time series panel
- Problem: Lots of data points per correlation

**Recommendation:** Option A for now - simpler and looks just as good.

**Time:** 4 hours

---

### 2.2 Venue Map Dashboard

**Problem:** No spatial awareness of where nodes are located relative to each other and the stage.

**Fix:** Use Grafana's Geomap panel (built-in, no plugin needed).

**Requirements:**
1. Store node coordinates (lat/lon or relative x/y) in config
2. Write location data to InfluxDB with coordinates
3. Create Geomap panel with nodes as markers, colored by dB level

**Node Configuration:**
```json
{
  "nodes": {
    "stage": {"x": 0, "y": 0, "type": "reference"},
    "dance_floor": {"x": 10, "y": 5, "type": "remote"},
    "back_bar": {"x": 30, "y": 0, "type": "remote"},
    "neighbor": {"x": 100, "y": 20, "type": "remote"}
  }
}
```

**Alternative:** Use Grafana's Canvas panel for custom venue layout with drag-and-drop positioning.

**Time:** 4 hours

---

### 2.3 Distance Radar Visualization

**Problem:** Calculated distances are shown as numbers, but a radar/sonar style visualization would be much more intuitive.

**Fix:** Create a canvas panel with:
- Stage at center
- Concentric circles at 10m, 25m, 50m, 100m
- Nodes positioned at their calculated distance
- Nodes colored by dB level

**ASCII mockup:**
```
                    100m
           ╭─────────────────────╮
          ╱    50m                ╲
         ╱   ╭───────────╮        ╲
        │   ╱    25m      ╲   ●    │  ← neighbor (95m)
        │  │  ╭─────╮      │       │
        │  │ │  10m  │     │       │
        │  │ │   ●   │ ●   │       │  ← back_bar (28m)
        │  │ │ STAGE │     │       │
        │  │  ╰─────╯      │       │
        │   ╲    ●        ╱        │  ← dance_floor (12m)
         ╲   ╰───────────╯        ╱
          ╲                      ╱
           ╰─────────────────────╯
```

**Implementation:** Grafana Canvas panel with dynamic positioning based on distance values.

**Time:** 6 hours

---

## 3. RPi Deployment (Fleet Management)

### 3.1 Pre-built Pi Image with Cloud-Init

**Problem:** Setting up each Pi manually is tedious and error-prone.

**Fix:** Create a pre-configured image using Raspberry Pi Imager's cloud-init support.

**Cloud-init user-data:**
```yaml
#cloud-config
hostname: bass-sentry-node
manage_etc_hosts: true

users:
  - name: bass
    groups: [adm, audio, video, plugdev]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ssh-rsa AAAA... your-key-here

packages:
  - git
  - python3-venv
  - python3-pip
  - portaudio19-dev

runcmd:
  - git clone https://github.com/yourrepo/bass-sentry /home/bass/bass-sentry
  - cd /home/bass/bass-sentry && ./remote-node-setup.sh default.dag
```

**Workflow:**
1. Flash image with cloud-init
2. Boot Pi (auto-configures WiFi, clones repo, starts service)
3. Done

**Time:** 4 hours

---

### 3.2 Ansible Playbook for Fleet Deployment

**Problem:** Updating 20+ nodes manually is not feasible.

**Fix:** Create Ansible playbook for:
- Initial setup
- DAG file deployment
- Software updates
- Configuration changes

**inventory.yml:**
```yaml
all:
  children:
    reference_nodes:
      hosts:
        stage-node:
          ansible_host: 192.168.1.10
          dag_file: reference.dag
    remote_nodes:
      hosts:
        dance-floor:
          ansible_host: 192.168.1.11
          dag_file: remote-bass.dag
        back-bar:
          ansible_host: 192.168.1.12
          dag_file: remote-bass.dag
```

**playbook.yml:**
```yaml
- hosts: all
  tasks:
    - name: Pull latest code
      git:
        repo: https://github.com/yourrepo/bass-sentry
        dest: /home/bass/bass-sentry

    - name: Copy DAG file
      copy:
        src: "dag_files/{{ dag_file }}"
        dest: /home/bass/bass-sentry/remote-node/dag_files/

    - name: Restart service
      systemd:
        name: bass_sentry_remote_node
        state: restarted
```

**Usage:**
```bash
# Deploy to all nodes
ansible-playbook -i inventory.yml playbook.yml

# Deploy to specific node
ansible-playbook -i inventory.yml playbook.yml --limit dance-floor
```

**Time:** 4 hours

---

### 3.3 Calibration Workflow

**Problem:** No documented process for calibrating microphones. Different mics have different sensitivities.

**Fix:** Create calibration script and documentation.

**Calibration Process:**
1. Place calibrated SPL meter next to microphone
2. Play pink noise at known level (e.g., 94 dB)
3. Run calibration script that calculates offset
4. Store calibration offset in node config

**calibrate.py:**
```python
#!/usr/bin/env python3
"""Microphone calibration utility."""

import numpy as np
import sounddevice as sd

def calibrate(reference_db=94.0, duration=10):
    """Record audio and calculate calibration offset."""
    print(f"Playing 94 dB reference tone near microphone...")
    print(f"Recording for {duration} seconds...")

    audio = sd.rec(int(duration * 44100), samplerate=44100, channels=1)
    sd.wait()

    rms = np.sqrt(np.mean(audio ** 2))
    measured_db = 20 * np.log10(rms / (2**15)) + 120  # Assuming 16-bit, 120 dB reference

    offset = reference_db - measured_db

    print(f"Measured: {measured_db:.1f} dB")
    print(f"Reference: {reference_db:.1f} dB")
    print(f"Calibration offset: {offset:+.1f} dB")

    return offset

if __name__ == "__main__":
    offset = calibrate()
    print(f"\nAdd this to your DAG config:")
    print(f'  "calibration_offset": {offset:.1f}')
```

**Time:** 2 hours

---

## 4. Additional Dashboards

### 4.1 Event Manager Dashboard

**Problem:** No high-level view for non-technical event managers.

**Fix:** Create simplified dashboard showing:
- Overall status: "All systems nominal" / "Warning" / "Critical"
- Compliance status: "Within limits" / "Approaching limit" / "Over limit"
- Complaint risk indicator
- Simple recommendations

**Panels:**
1. **Big Status Indicator** - Single stat, full width, huge font
2. **Compliance Timeline** - How long at each level today
3. **Comparison to Limit** - Current vs allowed, as percentage
4. **Recommendation Text** - "Consider reducing bass by 3 dB"

**Time:** 3 hours

---

### 4.2 Alerting Configuration

**Problem:** No alerts configured. System could exceed limits without notification.

**Fix:** Configure Grafana alerts for:
- dB level exceeds threshold for X minutes
- Node offline for Y minutes
- Data quality drops below Z%

**Alert Rules:**
```yaml
groups:
  - name: bass-sentry
    rules:
      - alert: HighDBLevel
        expr: avg_over_time(dBSPL{location="neighbor"}[5m]) > 65
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Neighbor noise level high"

      - alert: NodeOffline
        expr: time() - max(heartbeat_timestamp) > 120
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Node {{ $labels.node }} offline"
```

**Notification Channels:**
- Slack/Discord webhook
- Email
- PagerDuty (for critical)

**Time:** 2 hours

---

### 4.3 Mobile-Optimized View

**Problem:** Current dashboards work on mobile but aren't optimized for it.

**Fix:** Create dedicated mobile dashboard with:
- Single column layout
- Large touch targets
- Essential metrics only
- Swipe between locations

**Design:**
```
┌─────────────────────┐
│     DANCE FLOOR     │
│                     │
│    ┌───────────┐    │
│    │           │    │
│    │    98     │    │
│    │    dB     │    │
│    │           │    │
│    └───────────┘    │
│                     │
│   ● ● ● ○ ○         │  ← Location dots
│                     │
│  [< PREV]  [NEXT >] │
└─────────────────────┘
```

**Time:** 2 hours

---

## 5. Future: Active Control

### 5.1 Suggested Adjustments Display

**Problem:** System shows data but doesn't provide actionable guidance.

**Fix:** Calculate and display suggested adjustments based on:
- Current level vs target
- Trend direction
- Time of night (quieter limits later)

**Display:**
```
┌─────────────────────────────────────┐
│  SUGGESTED ADJUSTMENT               │
│                                     │
│  Bass: -3 dB                        │
│  Main: OK                           │
│                                     │
│  Reason: Neighbor trending up       │
│  Confidence: High                   │
└─────────────────────────────────────┘
```

**Time:** 4 hours

---

### 5.2 Automatic Limiter Integration (Future)

**Problem:** Manual adjustment is reactive, not proactive.

**Potential Solution:** Integration with:
- Hardware limiters (analog control voltage)
- Software limiters (OSC protocol)
- DJ software (MIDI)

**Safety Requirements:**
- Maximum adjustment rate (1 dB/second)
- Minimum level floor (can't cut audio completely)
- Physical override switch
- Comprehensive logging
- Liability considerations

**Recommendation:** Phase 2 feature. Get manual workflow right first.

**Time:** Unknown (significant)

---

## 6. Implementation Order

**Phase 1: Quick Wins (Day 1)**
1. Fix distances dashboard provisioning
2. Add template variables
3. Configure basic alerting

**Phase 2: Node Visibility (Day 2)**
4. Write heartbeats to InfluxDB
5. Create node health panel
6. Add node health to overview dashboard

**Phase 3: Cool Visualizations (Days 3-4)**
7. Cross-correlation waveform image generation
8. Venue map dashboard
9. Distance radar visualization

**Phase 4: Fleet Management (Day 5)**
10. Cloud-init Pi image
11. Ansible playbook
12. Calibration workflow

**Phase 5: Polish (Day 6)**
13. Event manager dashboard
14. Mobile-optimized view
15. Suggested adjustments display

---

## 7. Verification Checklist

After implementation:

- [ ] All dashboards load automatically on fresh `docker compose up`
- [ ] Template variables populate with actual locations
- [ ] Node health shows all connected nodes
- [ ] Cross-correlation visualization updates in real-time
- [ ] Venue map shows correct node positions
- [ ] Alerts fire and notify correctly
- [ ] New Pi can be deployed in < 10 minutes
- [ ] Mobile dashboard is usable on phone
- [ ] Non-technical user can understand event manager dashboard

---

**Document Version:** 1.0
**Created:** January 2025
**Status:** Ready for Implementation
