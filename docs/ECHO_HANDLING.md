# Echo Handling in Bass Sentry

**Problem**: Real venues have wall reflections creating echoes that can confuse cross-correlation.

**TL;DR**: Current system uses "strongest peak" which works in most cases. Enhanced strategies available for reverberant environments.

---

## How Echoes Appear in Cross-Correlation

When sound travels from stage to remote sensor via multiple paths:

```
Direct Path (10m):     Stage ──────────→ Remote      29ms
Wall Reflection (15m): Stage ──→ Wall ──→ Remote      44ms
Corner Echo (20m):     Stage ──→ Corners ──→ Remote   58ms
```

**Correlation function shows multiple peaks:**

```
Correlation
    │
1200│     Direct (29ms)
    │        █
 800│        █      Echo 1 (44ms)    Echo 2 (58ms)
    │        █         ▄                 ▃
 400│        █         ▄                 ▃
    │════════█═════════▄═════════════════▃═══════> Time (ms)
    0       29        44                58
```

---

## Current System Behavior

**File**: `master-node/data_handler.py`

```python
peak_idx = np.argmax(np.abs(cc))  # Finds STRONGEST peak
```

### ✅ Works Well When:
1. **Direct path is strongest** (typical for open spaces)
   - Inverse square law: closer = stronger
   - Wall absorption weakens echoes

2. **Clear line-of-sight**
   - No barriers between stage and remote
   - Minimal reflective surfaces

3. **Outdoor or warehouse venues**
   - High ceilings reduce floor/ceiling reflections
   - Distant walls minimize echoes

### ❌ Fails When:
1. **Blocked direct path**
   ```
   Stage ──X── Remote    Direct: Blocked
        └──→ Wall ──→    Echo: Stronger!
   ```
   **Result**: Detects echo → reports WRONG distance

2. **Highly reverberant space**
   - Concert hall with parallel walls
   - Small room with hard surfaces
   - Multiple echoes of similar strength
   **Result**: Peak selection becomes ambiguous

3. **Corner placement**
   - Remote in corner gets strong perpendicular reflections
   - Two-wall echo might overwhelm direct path
   **Result**: Measures 2× actual distance

---

## Enhanced Strategies

**File**: `master-node/correlation_strategies.py`

### Strategy 1: Strongest Peak (Current Default)
```python
from correlation_strategies import StrongestPeakStrategy

strategy = StrongestPeakStrategy()
peak_idx, delay, metadata = strategy.find_peak(correlation, lags, sample_rate)
```

**Best for**:
- ✅ Open floor plans
- ✅ Outdoor events
- ✅ Warehouses with high ceilings
- ✅ Good line-of-sight

**Advantages**:
- Simple and fast
- Works 90% of the time
- Highest confidence when single clear peak

**Limitations**:
- Assumes direct path is strongest
- Can pick wrong peak if direct path blocked

---

### Strategy 2: First Peak Above Threshold ⭐ RECOMMENDED FOR REVERBERANT SPACES
```python
from correlation_strategies import FirstPeakStrategy

strategy = FirstPeakStrategy(threshold_ratio=0.3)
peak_idx, delay, metadata = strategy.find_peak(correlation, lags, sample_rate)
```

**Best for**:
- ✅ Concert halls
- ✅ Small to medium venues
- ✅ Reverberant environments
- ✅ When distance accuracy is critical

**How it works**:
1. Find ALL peaks above 30% of maximum
2. Return the FIRST peak (shortest delay)
3. Direct path always arrives first (shortest distance)
4. Echoes arrive later (longer path)

**Advantages**:
- ✅ Robust to blocked direct path
- ✅ Always finds shortest path (most accurate distance)
- ✅ Rejects distant echoes automatically

**Limitations**:
- Requires proper threshold tuning
- Might pick noise peak if threshold too low

**Threshold guidance**:
- `0.3` (30%): Standard reverberant space
- `0.2` (20%): Highly reverberant (many echoes)
- `0.4` (40%): Conservative (fewer false positives)

---

### Strategy 3: Multi-Peak Analysis
```python
from correlation_strategies import MultiPeakStrategy

strategy = MultiPeakStrategy(threshold_ratio=0.2, max_peaks=5)
peak_idx, delay, metadata = strategy.find_peak(correlation, lags, sample_rate)

# metadata['peaks'] contains all detected peaks
# metadata['environment'] = 'clean' | 'moderate_echoes' | 'highly_reverberant'
# metadata['echo_delays_ms'] = [45.2, 58.7, ...]  # Secondary peaks
```

**Best for**:
- ✅ Room acoustics analysis
- ✅ Debugging echo issues
- ✅ Visualizing sound propagation
- ✅ Research and development

**Returns**:
- Primary peak (for distance calculation)
- ALL significant peaks with metadata
- Environment classification
- Echo delay times

**Use cases**:
- Identify reflective surfaces
- Detect acoustic problems
- Tune placement of remote nodes
- Generate echo visualizations

---

### Strategy 4: Windowed Search
```python
from correlation_strategies import WindowedSearchStrategy

# Search only between 5m and 50m
strategy = WindowedSearchStrategy(min_distance_m=5, max_distance_m=50)
peak_idx, delay, metadata = strategy.find_peak(correlation, lags, sample_rate)
```

**Best for**:
- ✅ Known approximate distances
- ✅ Multiple rooms/spaces
- ✅ Rejecting implausible peaks

**How it works**:
- Convert distance range to time window
- Search only within that window
- Reject peaks outside expected range

**Advantages**:
- Eliminates impossible distances
- Useful when layout is known
- Rejects cross-talk from adjacent venues

**Example**:
```python
# Venue is 20m × 30m, stage at one end
# Maximum possible distance is ~36m (diagonal)
# Minimum is ~5m (front of stage)
strategy = WindowedSearchStrategy(min_distance_m=5, max_distance_m=40)
```

---

## Practical Recommendations

### Default Configuration (Covers 90% of venues)
```python
# In master-node/data_handler.py
from correlation_strategies import get_correlation_strategy

strategy = get_correlation_strategy('auto')  # Uses strongest peak
```

### For Reverberant Venues
```python
strategy = get_correlation_strategy('reverberant')  # Uses first peak, threshold=0.2
```

### For Echo Debugging
```python
strategy = get_correlation_strategy('multi_path')  # Returns all peaks
```

### Custom Configuration
```python
from correlation_strategies import FirstPeakStrategy

strategy = FirstPeakStrategy(
    threshold_ratio=0.25,      # 25% of max correlation
    min_peak_height=100        # Absolute minimum correlation value
)
```

---

## How to Choose Strategy

### Decision Tree

```
Is your venue outdoors or warehouse with high ceiling?
└─ YES → Use "strongest peak" (current default)
└─ NO  → Continue...

Do you have reverberant spaces (concert hall, small room)?
└─ YES → Use "first peak" with threshold=0.3
└─ NO  → Continue...

Do echoes seem to be causing incorrect distances?
└─ YES → Use "first peak" with threshold=0.2
           OR Use "multi-peak" for analysis
└─ NO  → Use "strongest peak" (current default)

Do you know the approximate distance range?
└─ YES → Use "windowed search" for extra robustness
```

### Environmental Guide

| Environment | Strategy | Settings |
|-------------|----------|----------|
| Outdoor festival | Strongest Peak | (default) |
| Warehouse | Strongest Peak | (default) |
| Open floor plan | Strongest Peak | (default) |
| Concert hall | First Peak | threshold=0.3 |
| Theater | First Peak | threshold=0.3 |
| Small venue | First Peak | threshold=0.2 |
| Club with hard walls | First Peak | threshold=0.2 |
| Multi-room space | Windowed Search | Set distance range |
| Research/debugging | Multi-Peak | max_peaks=5 |

---

## Integration with Existing System

### Option 1: Global Strategy (All Nodes)
```python
# In master-node/data_handler.py

from correlation_strategies import get_correlation_strategy

class ChunkToCCStream(DataProcessor):
    def __init__(self, environment='auto'):
        # ...
        self.correlation_strategy = get_correlation_strategy(environment)

    def rcc(self, sig1, sig2, sample_rate):
        # ... normalization and correlation ...

        # Replace:
        # peak_idx = np.argmax(np.abs(cc))

        # With:
        peak_idx, delay, metadata = self.correlation_strategy.find_peak(
            cc, lags, sample_rate
        )

        # metadata contains:
        # - 'confidence': 0-1 reliability score
        # - 'num_peaks': Number of significant peaks
        # - 'environment': Environmental classification
        # - 'peaks': All peak information (multi-peak only)

        return db, delay, metadata['confidence']
```

### Option 2: Per-Node Strategy
```python
# Different strategies for different locations
node_strategies = {
    'dance_floor': 'auto',          # Open space
    'back_bar': 'reverberant',      # Near walls
    'balcony': 'first_peak',        # Complex acoustics
    'vip_booth': 'windowed'         # Known distance range
}
```

### Option 3: Adaptive Strategy
```python
# Start with strongest peak
# If confidence < 0.7, try first peak
# If still low confidence, use multi-peak analysis

def adaptive_correlation(correlation, lags, sample_rate):
    # Try strongest peak
    strategy1 = StrongestPeakStrategy()
    idx1, delay1, meta1 = strategy1.find_peak(correlation, lags, sample_rate)

    if meta1['confidence'] > 0.7:
        return idx1, delay1, meta1  # Good confidence, use it

    # Low confidence, try first peak
    strategy2 = FirstPeakStrategy(threshold_ratio=0.3)
    idx2, delay2, meta2 = strategy2.find_peak(correlation, lags, sample_rate)

    # Return whichever has higher confidence
    if meta2['confidence'] > meta1['confidence']:
        return idx2, delay2, meta2
    else:
        return idx1, delay1, meta1
```

---

## Monitoring Echo Issues

### Signs of Echo Problems

1. **Unstable distance readings**
   - Distance jumps between values (e.g., 10m → 15m → 10m)
   - Indicates peak selection is switching between direct/echo

2. **Multiple distance modes in histogram**
   - Histogram shows two distinct peaks
   - Suggests system alternating between direct path and echo

3. **Implausible distances**
   - Distance > venue dimensions
   - Distance increases when node moves closer
   - Clear indicator of echo detection

### Debugging Tools

#### 1. Multi-Peak Analysis
```python
from correlation_strategies import MultiPeakStrategy

strategy = MultiPeakStrategy(max_peaks=5)
peak_idx, delay, metadata = strategy.find_peak(correlation, lags, sample_rate)

print(f"Environment: {metadata['environment']}")
print(f"Number of peaks: {metadata['num_peaks']}")
print("All peaks:")
for peak in metadata['peaks']:
    print(f"  Delay: {peak['delay_ms']:.1f}ms, "
          f"Distance: {peak['distance_m']:.1f}m, "
          f"Strength: {peak['relative_strength']:.2f}")
```

#### 2. Correlation Viewer
```bash
# Shows full correlation function with echo visualization
python tools/live_correlation_viewer.py --mode mqtt
```

Orange dotted lines show detected echoes.

#### 3. Grafana Dashboard
Add panel showing distance stability (std deviation over 5 minutes).

---

## Future Enhancements

### Machine Learning Approach
```python
# Train classifier on labeled correlation functions
# Features: peak heights, delays, correlation shape
# Output: "direct" vs "echo" classification for each peak

def ml_peak_classification(correlation):
    peaks = detect_all_peaks(correlation)
    features = extract_features(peaks)
    predictions = classifier.predict(features)
    primary_peak = peaks[predictions == 'direct'][0]
    return primary_peak
```

### Environmental Calibration
```python
# Learn venue acoustics during soundcheck
# Build map of expected echo patterns
# Use for real-time echo rejection during event

def calibrated_correlation(correlation, node_id):
    expected_echoes = echo_map[node_id]
    return reject_known_echoes(correlation, expected_echoes)
```

### Beam forming (Multiple Reference Mics)
```python
# Use array of reference microphones
# Beam forming to focus on direct path
# Spatial filtering to reject echoes

def beamformed_correlation(remote_signal, ref_array):
    # Delay-and-sum beamforming toward remote node
    focused_reference = beamform(ref_array, direction=node_direction)
    return correlate(remote_signal, focused_reference)
```

---

## Summary

| Aspect | Solution |
|--------|----------|
| **Current System** | Strongest peak - works 90% of time |
| **Echo-Prone Venues** | Use FirstPeakStrategy (threshold=0.3) |
| **Debugging** | Use MultiPeakStrategy for analysis |
| **Known Distances** | Use WindowedSearchStrategy |
| **Detection** | Monitor distance stability & histograms |
| **Visualization** | Use correlation viewer to see echoes |

**Bottom line**: Current system handles echoes well in typical venues. Enhanced strategies available when needed.

For most deployments, **start with default and only change if you see unstable distance readings**.
