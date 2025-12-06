# Bass Sentry Tools

## Live Correlation Viewer

**File**: `live_correlation_viewer.py`

Real-time visualization tool that shows:
- Cross-correlation functions with visible peaks and echoes
- Histogram of recent correlation measurements
- Data quality and confidence metrics

### Features

1. **Correlation Function Display**: See the full correlation waveform, not just the peak
2. **Echo Detection**: Automatically marks secondary peaks (potential echoes/reflections)
3. **Peak Histogram**: Distribution of measurements over time shows stability
4. **Statistics**: Mean delay, standard deviation, distance, quality metrics

### Usage

#### Demo Mode (No Hardware Required)
```bash
python tools/live_correlation_viewer.py --mode demo
```
Generates synthetic correlation data to demonstrate the interface.

#### MQTT Mode (Live Data)
```bash
pip install paho-mqtt matplotlib numpy
python tools/live_correlation_viewer.py \
  --mode mqtt \
  --mqtt-broker localhost \
  --mqtt-topic correlation/#
```
**Note**: Currently correlation functions are not transmitted via MQTT (only summary statistics). This mode will show peak histograms but not full correlation functions.

#### InfluxDB Mode (Historical Data)
```bash
pip install influxdb-client matplotlib numpy
python tools/live_correlation_viewer.py \
  --mode influxdb \
  --influxdb-url http://localhost:8086 \
  --influxdb-bucket bass_sentry
```
**Note**: Full correlation functions are not stored in InfluxDB (too much data). This mode shows peak histograms from stored measurements.

### Interpretation

#### Correlation Function Plot
- **X-axis**: Time lag in milliseconds
- **Y-axis**: Correlation strength
- **Red dashed line**: Main peak (detected delay)
- **Orange dotted lines**: Secondary peaks (echoes/reflections)

**Echoes** appear as additional peaks at different time lags. They indicate:
- Sound reflections from walls/surfaces
- Multiple propagation paths
- Reverberant environments

#### Peak Histogram
- Shows distribution of detected delays over recent measurements
- Tight distribution = stable, consistent measurements
- Wide distribution = variable conditions or measurement noise
- Current value marked with red dashed line

#### Statistics Box
- **Mean ± Std**: Average delay and variability
- **Distance**: Calculated distance (delay × 343 m/s)
- **Quality**: Percentage of good data (packet loss tolerance)
- **Confidence**: Overall reliability score

### Extending to Store Full Correlation Functions

To enable full correlation visualization from live data, you would need to:

1. **Modify master node** to publish full correlation arrays
2. **Use binary encoding** (not JSON) to reduce bandwidth
3. **Subscribe directly** to correlation data before InfluxDB storage

Example modification to `master-node/data_handler.py`:
```python
# After correlation, publish full function
correlation_data = {
    'node_id': remote_id,
    'delay_ms': tau * 1000,
    'correlation_func': correlation.tolist()[:1000],  # Subsample to reduce size
    'timestamp': time.time()
}
mqtt_client.publish(f'correlation_raw/{remote_id}',
                   msgpack.packb(correlation_data))  # Binary encoding
```

### Future Enhancements

- **Waterfall plot**: Time-evolving correlation function
- **3D visualization**: Frequency × Time × Correlation
- **Multi-echo tracking**: Track individual echo paths over time
- **Export**: Save correlation functions to file for offline analysis

