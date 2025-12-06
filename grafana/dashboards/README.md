# Grafana Dashboards

## Bass Sentry - Physical Distances

**File**: `bass-sentry-distances.json`

This dashboard provides real-time monitoring of physical distances calculated from cross-correlation time delays.

### Panels

1. **Distance from Stage (meters)** - Main graph showing calculated distance = delay × 0.343 m/s
2. **Time Delay (milliseconds)** - Raw correlation delay values
3. **Correlation Strength (dB)** - Signal strength of correlation peak
4. **Data Quality (%)** - Percentage of good data (accounts for packet loss)
5. **Confidence Score** - Combined metric: correlation_coefficient × data_quality
6. **Current Distances (Stat)** - Latest distance values for all nodes

### Installation

#### Option 1: Via Grafana UI
1. Open Grafana: http://localhost:3000
2. Go to Dashboards → Import
3. Upload `bass-sentry-distances.json`

#### Option 2: Via API
```bash
curl -X POST -H "Content-Type: application/json" \
  -d @bass-sentry-distances.json \
  http://admin:admin@localhost:3000/api/dashboards/db
```

#### Option 3: Provisioning (Persistent)
Add to `docker-compose.yml`:
```yaml
grafana:
  volumes:
    - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
```

### Important Notes

**Positioning Limitation**: With a single reference point (stage), the system calculates **radial distance** only, not X,Y coordinates.

To determine position:
- **Distance only**: Current system (one reference point)
- **2D positioning**: Requires 3+ reference speakers for triangulation
- **Manual**: User can enter known node positions and compare with detected distances

### Metrics Reference

| Field | Unit | Description |
|-------|------|-------------|
| delay_ms | milliseconds | Time delay from cross-correlation |
| distance_m | meters | delay_ms × 0.343 (speed of sound) |
| db | decibels | Correlation peak strength |
| correlation_coef | 0-1 | Normalized correlation coefficient |
| data_quality | 0-1 | Ratio of good/interpolated chunks |
| confidence | 0-1 | correlation_coef × data_quality |

### Thresholds

**Data Quality**:
- 🔴 Red: <60% (correlation skipped)
- 🟡 Yellow: 60-90% (marginal quality)
- 🟢 Green: >90% (excellent quality)

**Confidence**:
- 🔴 Red: <0.5 (unreliable)
- 🟡 Yellow: 0.5-0.8 (usable)
- 🟢 Green: >0.8 (high confidence)

### Troubleshooting

**No data showing?**
- Check InfluxDB connection in Grafana data sources
- Verify `correlation` measurement exists: `influx -database bass_sentry -execute "SHOW MEASUREMENTS"`
- Check master node is running correlation: `docker-compose logs master_node`

**Distances seem wrong?**
- Verify speed of sound (343 m/s at 20°C, 331 m/s at 0°C)
- Check time synchronization between nodes
- Verify reference node is properly tagged with `tags: ["reference"]` in DAG file
