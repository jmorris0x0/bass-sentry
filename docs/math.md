# Bass Sentry: Mathematical Foundations

## Executive Summary

Bass Sentry uses cross-correlation to extract the venue's sound contribution at remote locations, mathematically separating it from environmental noise. The key formula:

```
venue_dB = total_remote_dB + 20·log₁₀(ρ)
```

Where ρ is the normalized cross-correlation coefficient. This formula cleanly subtracts environmental noise, yielding the venue's contribution regardless of confounding noise sources.

---

## 1. The Problem

A music venue produces sound. Neighbors hear a mix of:
- **Venue sound** (what we want to measure)
- **Environmental noise** (traffic, wind, dogs, HVAC, etc.)

Standard sound level meters measure **total** dB. They cannot distinguish venue contribution from environmental noise.

**Goal:** Extract the venue's dB contribution as if environmental noise doesn't exist.

---

## 2. Signal Model

### At the Reference Microphone (Stage)

```
r(t) = venue signal
```

This is our "ground truth" - the pure venue sound.

### At the Remote Microphone (Neighbor)

```
x(t) = α·r(t - τ) + n(t)
```

Where:
| Symbol | Meaning |
|--------|---------|
| α | Attenuation factor (0 < α < 1) due to distance, walls, air absorption |
| τ | Propagation delay = distance / 343 m/s |
| n(t) | Environmental noise, **uncorrelated** with venue signal |

The remote mic hears a delayed, attenuated copy of the venue signal, plus noise.

---

## 3. Cross-Correlation Theory

### Definition

The cross-correlation between signals x(t) and r(t) at lag L:

```
R_xr(L) = E[x(t) · r(t - L)]
```

This measures similarity between x and a time-shifted version of r.

### Applying to Our Signal Model

```
R_xr(L) = E[x(t) · r(t - L)]
        = E[(α·r(t - τ) + n(t)) · r(t - L)]
        = α·E[r(t - τ) · r(t - L)] + E[n(t) · r(t - L)]
```

**Key insight:** Since n(t) is uncorrelated with r(t):

```
E[n(t) · r(t - L)] → 0  (as averaging time increases)
```

Therefore:

```
R_xr(L) = α · R_rr(L - τ)
```

The cross-correlation equals a scaled, shifted version of the **autocorrelation** of the reference signal. The noise term vanishes.

### Finding the Peak

The autocorrelation R_rr peaks at lag 0:

```
R_rr(0) = E[r²] = r_rms²
```

Therefore R_xr peaks at lag τ (the propagation delay):

```
R_xr(τ) = α · r_rms²
```

---

## 4. Extracting Venue Amplitude

### Solving for Attenuation

From the cross-correlation peak:

```
α = R_xr(τ) / r_rms²
```

### Venue RMS at Remote

The venue signal's RMS amplitude at the remote location:

```
s_rms = α · r_rms = R_xr(τ) / r_rms
```

### Normalized Correlation Coefficient

The normalized cross-correlation coefficient ρ is:

```
ρ = R_xr(τ) / (x_rms · r_rms)
```

Where x_rms is the total RMS at the remote (venue + noise).

Rearranging:

```
R_xr(τ) = ρ · x_rms · r_rms
```

### The Key Result

Substituting into our expression for s_rms:

```
s_rms = R_xr(τ) / r_rms
      = ρ · x_rms · r_rms / r_rms
      = ρ · x_rms
```

**The venue amplitude at remote equals ρ times the total amplitude.**

### Converting to Decibels

```
venue_dB = 20 · log₁₀(s_rms / reference)
         = 20 · log₁₀(ρ · x_rms / reference)
         = 20 · log₁₀(x_rms / reference) + 20 · log₁₀(ρ)
         = total_remote_dB + 20 · log₁₀(ρ)
```

---

## 5. The Formula

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   venue_dB = total_remote_dB + 20 · log₁₀(ρ)           │
│                                                         │
│   Where:                                                │
│   • total_remote_dB = measured dB at remote location    │
│   • ρ = normalized cross-correlation coefficient        │
│         at the propagation delay lag                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

This formula extracts the venue's contribution regardless of environmental noise level.

---

## 6. Proof: Anechoic Chamber Test

### Test Setup

- Reference microphone at stage: 90 dB SPL
- Remote microphone 30m away: expects 80 dB SPL (10 dB attenuation from distance)
- Environmental noise: variable

### Scenario 1: No Environmental Noise

| Parameter | Value |
|-----------|-------|
| Venue at remote | 80 dB |
| Noise at remote | -∞ dB (none) |
| Total at remote | 80 dB |
| ρ | 1.0 (perfect correlation) |
| **Computed venue_dB** | 80 + 20·log₁₀(1.0) = **80 dB** ✓ |

### Scenario 2: Moderate Environmental Noise (70 dB)

Converting to linear amplitude (relative units):
- Venue amplitude: 10^(80/20) = 10,000
- Noise amplitude: 10^(70/20) = 3,162

Total power (uncorrelated signals add in power):
```
total_power = 10,000² + 3,162² = 110,000,000
total_rms = √110,000,000 ≈ 10,488
total_dB = 20·log₁₀(10,488) ≈ 80.4 dB
```

Correlation coefficient:
```
ρ = venue_rms / total_rms = 10,000 / 10,488 ≈ 0.953
```

| Parameter | Value |
|-----------|-------|
| Total at remote | 80.4 dB |
| ρ | 0.953 |
| **Computed venue_dB** | 80.4 + 20·log₁₀(0.953) = 80.4 - 0.4 = **80 dB** ✓ |

### Scenario 3: Loud Environmental Noise (85 dB, louder than venue)

- Venue amplitude: 10,000
- Noise amplitude: 10^(85/20) = 17,783
- Total RMS: √(10,000² + 17,783²) ≈ 20,396
- Total dB: 20·log₁₀(20,396) ≈ 86.2 dB
- ρ = 10,000 / 20,396 ≈ 0.490

| Parameter | Value |
|-----------|-------|
| Total at remote | 86.2 dB |
| ρ | 0.490 |
| **Computed venue_dB** | 86.2 + 20·log₁₀(0.490) = 86.2 - 6.2 = **80 dB** ✓ |

### Scenario 4: Very Loud Environmental Noise (95 dB)

- Venue amplitude: 10,000
- Noise amplitude: 10^(95/20) = 56,234
- Total RMS: √(10,000² + 56,234²) ≈ 57,116
- Total dB: ≈ 95.1 dB
- ρ = 10,000 / 57,116 ≈ 0.175

| Parameter | Value |
|-----------|-------|
| Total at remote | 95.1 dB |
| ρ | 0.175 |
| **Computed venue_dB** | 95.1 + 20·log₁₀(0.175) = 95.1 - 15.1 = **80 dB** ✓ |

**The venue contribution remains 80 dB regardless of environmental noise level.**

---

## 7. Assumptions and Limitations

### Required Assumptions

1. **Uncorrelated noise**: Environmental noise must be statistically independent of the venue signal. This holds for traffic, wind, HVAC, etc. It would NOT hold if a nearby venue played the same music.

2. **Sufficient averaging**: The noise term E[n·r] approaches zero only with enough samples. Longer measurement windows improve accuracy.

3. **Linear propagation**: Sound travels without distortion. Clipping at microphones or extreme nonlinearities violate this.

4. **Stationary signals**: Statistics (RMS, correlation) must be stable over the measurement window. Rapid changes reduce accuracy.

### Practical Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Low correlation (ρ < 0.1) | High uncertainty in venue_dB | Longer averaging, better mics |
| Multipath reflections | Multiple correlation peaks | Use highest peak, or model reflections |
| Non-stationary venue signal | Time-varying α | Use short windows, track α over time |
| Correlated noise sources | Noise doesn't cancel | Identify and exclude correlated sources |

### Minimum Detectable Signal

When ρ is very small, the formula becomes numerically unstable:

```
20·log₁₀(0.01) = -40 dB correction
20·log₁₀(0.001) = -60 dB correction
```

Practical limit: venue signal should be at least -30 dB relative to noise for reliable extraction (ρ > 0.03).

---

## 8. Comparison to Standard Methods

### Standard Method: On/Off Measurement (ISO 1996)

```
L_venue = 10·log₁₀(10^(L_on/10) - 10^(L_off/10))
```

| Aspect | Standard Method | Bass Sentry |
|--------|-----------------|-------------|
| Requires venue off? | Yes | No |
| Real-time? | No | Yes |
| Proves causation? | No (coincidental) | Yes (correlation) |
| Works in high noise? | No (fails if Δ < 3dB) | Yes |
| Continuous monitoring? | No | Yes |

### Why Cross-Correlation is Superior

1. **Proves causation**: Correlation mathematically proves the remote signal matches the venue. The standard method only shows "it got quieter" - could be coincidence.

2. **Real-time operation**: No need to stop the music. Continuous monitoring during events.

3. **Noise immunity**: Works even when venue contribution is buried in environmental noise.

4. **Temporal precision**: Knows exactly when venue sound arrives (delay τ).

---

## 9. Psychoacoustic Considerations

### Frequency Weighting

Raw dB SPL doesn't match human perception. Apply weighting:

| Weighting | Use Case | Bass Sentry Application |
|-----------|----------|------------------------|
| A-weighting (dBA) | General noise, speech | Standard compliance reporting |
| C-weighting (dBC) | Loud/low-frequency sound | **Recommended for bass monitoring** |
| Z-weighting (dBZ) | Unweighted, scientific | Raw measurements |

**Recommendation:** Report both dBA and dBC. C-weighting better represents low-frequency venue sound that travels far and penetrates walls.

### The "Quiet Moment" Problem

Environmental noise is transient. People complain when:
- Cars stop driving by
- Wind dies down
- The quiet reveals the bass

**Metric:** Venue audibility during quiet moments:

```
venue_audibility = venue_dB - LA90(total_remote)
```

Where LA90 = level exceeded 90% of time (the quiet baseline).

This answers: "When it's quiet, how much does the bass stand out?"

### Recommended Display

```
NEIGHBOR STATION
├── Venue Contribution: 58 dBC    ← Primary metric
├── Total Measured: 62 dBC
├── Background (LA90): 45 dBC
├── Venue Audibility: +13 dB      ← Above quiet baseline
└── Correlation: ✓ Confirmed (ρ = 0.74)
```

---

## 10. Implementation Notes

### Computing ρ in Practice

1. **Bandpass filter** both signals (e.g., 20-200 Hz for bass)
2. **Normalize** both signals to zero mean
3. **Cross-correlate** to find peak and lag
4. **Normalize** by RMS values to get ρ

```python
import numpy as np
from scipy import signal

def compute_venue_contribution(reference, remote, sample_rate):
    # Bandpass filter (20-200 Hz)
    sos = signal.butter(4, [20, 200], btype='band', fs=sample_rate, output='sos')
    ref_filt = signal.sosfilt(sos, reference)
    rem_filt = signal.sosfilt(sos, remote)

    # Normalize to zero mean
    ref_filt -= np.mean(ref_filt)
    rem_filt -= np.mean(rem_filt)

    # Cross-correlation
    correlation = signal.correlate(rem_filt, ref_filt, mode='full')
    lags = signal.correlation_lags(len(rem_filt), len(ref_filt), mode='full')

    # Find peak
    peak_idx = np.argmax(np.abs(correlation))
    peak_lag = lags[peak_idx]
    peak_value = correlation[peak_idx]

    # Normalize to get ρ
    rms_ref = np.sqrt(np.mean(ref_filt**2))
    rms_rem = np.sqrt(np.mean(rem_filt**2))
    rho = peak_value / (len(ref_filt) * rms_ref * rms_rem)

    # Compute venue contribution
    total_db = 20 * np.log10(rms_rem + 1e-10)
    venue_db = total_db + 20 * np.log10(abs(rho) + 1e-10)

    delay_seconds = peak_lag / sample_rate
    distance_meters = delay_seconds * 343

    return {
        'venue_db': venue_db,
        'total_db': total_db,
        'rho': rho,
        'delay_ms': delay_seconds * 1000,
        'distance_m': distance_meters
    }
```

### Averaging for Stability

Single-window measurements have variance. For stable readings:

```python
def averaged_venue_contribution(ref_chunks, rem_chunks, sample_rate, min_windows=10):
    results = []
    for ref, rem in zip(ref_chunks, rem_chunks):
        result = compute_venue_contribution(ref, rem, sample_rate)
        results.append(result)

    # Average in linear domain, then convert to dB
    venue_linear = [10**(r['venue_db']/20) for r in results]
    avg_linear = np.mean(venue_linear)
    avg_venue_db = 20 * np.log10(avg_linear)

    return {
        'venue_db': avg_venue_db,
        'rho': np.mean([r['rho'] for r in results]),
        'std_db': np.std([r['venue_db'] for r in results])
    }
```

---

## 11. Summary

Bass Sentry's cross-correlation approach provides:

1. **Clean venue extraction**: `venue_dB = total_dB + 20·log₁₀(ρ)` removes environmental noise mathematically.

2. **Proof of causation**: Correlation proves the sound originated from the venue.

3. **Real-time monitoring**: Continuous measurement during events without turning off the music.

4. **Noise immunity**: Works even when environmental noise exceeds venue contribution.

This is not merely an alternative to standard methods - it's superior for live event monitoring where the venue cannot be switched off for measurement.

---

## References

- ISO 1996-1:2016 - Acoustics: Description, measurement and assessment of environmental noise
- ISO 1996-2:2017 - Determination of sound pressure levels
- BS 4142:2014+A1:2019 - Methods for rating industrial and commercial sound
- Bendat, J.S. & Piersol, A.G. - "Random Data: Analysis and Measurement Procedures"
- IEC 61672-1 - Electroacoustics: Sound level meters
