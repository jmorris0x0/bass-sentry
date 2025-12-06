# External DSP Plan - Automatic Bass Control

**Goal**: Automatically limit bass levels using professional DSP hardware controlled by Bass Sentry.

**Key Advantage**: Audio never goes through Raspberry Pi - DSP hardware provides <1ms latency for audio processing while Bass Sentry sends control commands every 100-500ms.

---

## Architecture Overview

```
Remote Nodes (measure bass levels)
    ↓ MQTT
Master Node / Raspberry Pi (calculates what to do)
    ↓ Ethernet/MIDI/RS-232 (control commands only, NOT audio)
External DSP Unit (does actual limiting/EQ)
    ↓ Audio (< 1ms latency)
PA System
```

**Two separate paths**:
1. **Audio Path**: DJ → DSP → PA (<1ms latency through dedicated hardware)
2. **Control Path**: Remotes → Master → DSP (100-500ms latency, acceptable for bass)

**If Bass Sentry fails**: DSP continues passing audio normally (failsafe)

---

## Hardware Options

### Option 1: dbx DriveRack PA2 ($400) ⭐ RECOMMENDED

**Specifications**:
- Stereo 2-way or mono 3-way crossover
- 9-band parametric EQ per channel
- Limiters on all outputs
- Feedback suppression
- Control: Ethernet (HiQnet protocol), RS-232, USB, front panel
- Latency: <1ms

**Pros**:
- ✅ Industry standard in live sound
- ✅ Ethernet control (easy integration)
- ✅ Front panel override (DJ/engineer can disable)
- ✅ Can do both EQ and crossover approaches
- ✅ Reliable, venue-proven

**Cons**:
- ❌ More expensive than Behringer
- ❌ Proprietary control protocol (but documented)

**Where to buy**: Sweetwater, Guitar Center, Amazon

---

### Option 2: Behringer DCX2496 ($200)

**Specifications**:
- Stereo 3-way crossover (6 outputs)
- 9-band parametric EQ per output
- Limiter on each output
- Control: MIDI, RS-232, front panel
- Latency: <1ms

**Pros**:
- ✅ Half the price of DriveRack
- ✅ More outputs (better for complex setups)
- ✅ MIDI control (standardized protocol)
- ✅ Good sound quality

**Cons**:
- ❌ No Ethernet (MIDI only)
- ❌ Less intuitive interface
- ❌ Behringer reliability concerns (though this model is solid)

**Best for**: Venues with separate subs/mains already

---

### Option 3: BSS Soundweb London BLU-160 ($1200+)

**Specifications**:
- Fully programmable DSP
- Multiband dynamics (compress/limit per frequency band)
- Ethernet control (native)
- Industry standard

**Pros**:
- ✅ Can do everything
- ✅ Most flexible
- ✅ Best sound quality
- ✅ Ethernet native

**Cons**:
- ❌ Expensive
- ❌ Requires programming (HiQnet Audio Architect software)
- ❌ Overkill for most applications

**Best for**: Large venues, permanent installations

---

## Two Implementation Approaches

### Approach 1: Parametric EQ Reduction (Simpler)

**Use when**: Single full-range PA system (no separate subs)

**Signal Flow**:
```
DJ Mixer → DSP (applies EQ) → Full-Range PA
```

**How it works**:
1. Bass Sentry detects bass is too loud (e.g., -10 dBFS at remote location)
2. Master node calculates: "Need to reduce by 4 dB"
3. Sends command to DSP: "Set 50Hz EQ to -4dB"
4. DSP applies EQ reduction in real-time
5. All other frequencies pass through unchanged

**DSP Configuration**:
- Parametric EQ Band 1: 50 Hz, Q=1.0, Gain = variable (-6 to 0 dB)
- Parametric EQ Band 2: 80 Hz, Q=1.0, Gain = variable (-6 to 0 dB)
- Other bands: No change

**Control Example** (dbx DriveRack):
```python
# Reduce 50Hz by 3dB
send_command("SET EQ BAND 1 FREQ 50 GAIN -3 Q 1.0")

# Restore to flat (no reduction)
send_command("SET EQ BAND 1 FREQ 50 GAIN 0 Q 1.0")
```

**Pros**:
- ✅ Works with any PA setup
- ✅ No additional amps/speakers needed
- ✅ Easy to implement

**Cons**:
- ❌ EQ changes affect tonal balance
- ❌ Limited to ~6dB reduction (more sounds unnatural)
- ❌ Less transparent than compression

**Recommended for**: Small to medium venues, single PA system

---

### Approach 2: Crossover + Multiband Limiting (Better Sound Quality)

**Use when**: Separate subwoofers and main speakers

**Signal Flow**:
```
           ┌→ Low Pass (20-120 Hz) → Limiter (variable) → Sub Amp → Subwoofers
DJ Mixer → DSP ─┤
           └→ High Pass (120Hz+) → Direct → Main Amp → Main Speakers
```

**How it works**:
1. DSP splits signal at crossover point (e.g., 120 Hz)
2. Bass frequencies → Limiter (controlled by Bass Sentry)
3. Mids/Highs → Pass through unchanged
4. Bass Sentry adjusts limiter threshold based on remote measurements

**DSP Configuration**:
- Crossover: 120 Hz (Linkwitz-Riley 24dB/octave)
- Output 1 (Low): Limiter threshold = variable (-20 to -6 dBFS)
- Output 2 (High): No limiting

**Control Example** (dbx DriveRack):
```python
# Make bass limiter more aggressive
send_command("SET LIMITER OUTPUT 1 THRESHOLD -18")  # Tighter limiting

# Relax bass limiter
send_command("SET LIMITER OUTPUT 1 THRESHOLD -12")  # Gentler limiting
```

**Pros**:
- ✅ Only limits problematic frequencies
- ✅ Mids/highs unaffected (better sound quality)
- ✅ Can do aggressive limiting on bass without harming music
- ✅ Transparent, musical

**Cons**:
- ❌ Requires separate subs and mains
- ❌ Need separate amplifiers
- ❌ More complex setup

**Recommended for**: Professional venues, outdoor festivals, venues with existing sub/main split

---

## Control Protocol Implementation

### dbx DriveRack PA2 (HiQnet Ethernet)

**Connection**: Ethernet cable from Master Node to DriveRack

**Protocol**: HiQnet (proprietary but documented)

**Python Example**:
```python
import socket

class DriveRackController:
    def __init__(self, ip='192.168.1.100', port=3804):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ip, port))

    def set_eq_gain(self, band, gain_db):
        """Adjust EQ band gain (Approach 1)."""
        cmd = f"SET EQ BAND {band} GAIN {gain_db}\r\n"
        self.sock.send(cmd.encode())

    def set_limiter_threshold(self, output, threshold_db):
        """Adjust limiter threshold (Approach 2)."""
        cmd = f"SET LIMITER OUTPUT {output} THRESHOLD {threshold_db}\r\n"
        self.sock.send(cmd.encode())

# Usage
dsp = DriveRackController(ip='192.168.1.100')

# Reduce bass by 3dB
dsp.set_eq_gain(band=1, gain_db=-3)

# Or tighten sub limiter
dsp.set_limiter_threshold(output=1, threshold_db=-18)
```

**Documentation**: dbx HiQnet protocol specification (available from manufacturer)

---

### Behringer DCX2496 (MIDI)

**Connection**: USB-MIDI adapter from Master Node to DCX2496

**Protocol**: MIDI (standardized)

**Python Example**:
```python
import mido

class BehringerController:
    def __init__(self, port_name='DCX2496'):
        self.port = mido.open_output(port_name)

    def set_eq_gain(self, output, band, gain_db):
        """Adjust EQ gain via MIDI."""
        # Convert gain_db to MIDI value (0-127)
        # gain_db: -12 to +12 dB → MIDI: 0 to 127
        midi_value = int((gain_db + 12) * 127 / 24)
        midi_value = max(0, min(127, midi_value))

        # MIDI CC message (see DCX2496 MIDI implementation chart)
        cc_number = 20 + (output * 10) + band  # Example mapping
        self.port.send(mido.Message('control_change',
                                    control=cc_number,
                                    value=midi_value))

    def set_limiter_threshold(self, output, threshold_db):
        """Adjust limiter threshold via MIDI."""
        # threshold_db: -40 to 0 dB → MIDI: 0 to 127
        midi_value = int((threshold_db + 40) * 127 / 40)
        midi_value = max(0, min(127, midi_value))

        cc_number = 50 + output  # Example mapping
        self.port.send(mido.Message('control_change',
                                    control=cc_number,
                                    value=midi_value))

# Usage
dsp = BehringerController()
dsp.set_limiter_threshold(output=1, threshold_db=-18)
```

**Documentation**: Behringer DCX2496 MIDI implementation chart (in manual)

---

## Control Algorithm

### Simple Approach: Direct Mapping
```python
# Get maximum bass level from all remote nodes
max_bass_db = max(remote_measurements.values())

# Target: -20 dBFS, Maximum: -15 dBFS
if max_bass_db > -15:
    # Over maximum: reduce immediately
    reduction_db = -15 - max_bass_db
    dsp.set_eq_gain(band=1, gain_db=reduction_db)

elif max_bass_db > -20:
    # Between target and max: gentle reduction
    reduction_db = (-20 - max_bass_db) * 0.5  # Softer slope
    dsp.set_eq_gain(band=1, gain_db=reduction_db)

else:
    # Below target: no reduction
    dsp.set_eq_gain(band=1, gain_db=0)
```

### Better Approach: Smoothed PID Control
```python
class BassController:
    def __init__(self, setpoint=-20, Kp=0.3, Ki=0.05, Kd=0.02):
        self.setpoint = setpoint
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.integral = 0
        self.last_error = 0

    def update(self, measured_bass_db, dt=0.5):
        """Calculate EQ/limiter adjustment."""
        error = self.setpoint - measured_bass_db

        # PID calculation
        P = self.Kp * error
        self.integral += error * dt
        I = self.Ki * self.integral
        D = self.Kd * (error - self.last_error) / dt
        self.last_error = error

        reduction_db = P + I + D

        # Clamp to reasonable range
        reduction_db = max(-12, min(0, reduction_db))

        return reduction_db
```

---

## Implementation Steps

### Phase 1: Hardware Setup
1. **Purchase DSP unit** (dbx DriveRack PA2 recommended)
2. **Install in signal chain**:
   - Input: DJ mixer output
   - Output: PA system input (or separate sub/main amps)
3. **Configure DSP**:
   - Set up parametric EQ bands (50Hz, 80Hz, 100Hz)
   - OR set up crossover + limiters (if using separate subs)
4. **Connect control interface**:
   - Ethernet cable from Master Node to DSP
   - OR USB-MIDI adapter

### Phase 2: Software Integration
1. **Install control library**:
   - For dbx: HiQnet protocol library
   - For Behringer: python-mido (MIDI)
2. **Create DSP control module** on Master Node
3. **Integrate with existing Bass Sentry**:
   - Master node already calculates bass levels
   - Add: Send control commands to DSP
4. **Add Redis for fast data sharing** (optional, for lower latency)

### Phase 3: Testing
1. **Test in parallel** with existing monitoring (don't control yet)
2. **Log what commands would be sent**
3. **Verify measurements are accurate**
4. **Test manual control** (send commands, verify DSP responds)
5. **Enable automatic control** in safe environment

### Phase 4: Production
1. **Document override procedures** (DJ/engineer can disable)
2. **Set conservative thresholds** (only limit extreme levels)
3. **Monitor and tune** based on real-world performance
4. **Gradually make more aggressive** as confidence builds

---

## Recommended Configuration

### For Most Venues (Single PA):
- **Hardware**: dbx DriveRack PA2 ($400)
- **Approach**: Parametric EQ reduction (Approach 1)
- **Configuration**:
  - EQ Band 1: 50 Hz, Q=1.0, Gain = variable (0 to -6 dB)
  - EQ Band 2: 80 Hz, Q=1.0, Gain = variable (0 to -6 dB)
  - Control via Ethernet from Master Node
  - Update every 500ms (fast enough for bass)

### For Professional Venues (Separate Subs):
- **Hardware**: dbx DriveRack PA2 or Behringer DCX2496
- **Approach**: Crossover + multiband limiting (Approach 2)
- **Configuration**:
  - Crossover at 120 Hz (Linkwitz-Riley 24dB/oct)
  - Low output: Limiter threshold variable (-20 to -6 dBFS)
  - High output: Direct (no limiting)
  - Control via Ethernet or MIDI
  - Update every 500ms

---

## Safety Considerations

### Failsafe Modes
1. **If control connection lost**: DSP continues with last settings (gentle limiting)
2. **If remote measurements timeout**: Disable limiting (pass through)
3. **Manual override switch**: DJ can disable automatic control
4. **Rate limiting**: Don't change settings more than every 500ms (avoid rapid changes)

### Conservative Thresholds
- **Start gentle**: Only limit extreme levels (-10 dBFS+)
- **Monitor complaints**: If neighbors still complain, make more aggressive
- **Avoid over-limiting**: Don't reduce bass more than 6-10 dB (sounds bad)

### Override Capability
```python
# DJ override button/command
if dj_override_active:
    dsp.set_eq_gain(band=1, gain_db=0)  # Disable limiting
    log("DJ override active - automatic control disabled")
```

---

## Cost Breakdown

### Minimum Setup (Single PA):
- dbx DriveRack PA2: $400
- Ethernet cable (Cat5/6): $10
- **Total: $410**

### Professional Setup (Separate Subs):
- dbx DriveRack PA2: $400
- Ethernet cable: $10
- (Assumes existing separate sub/main amps)
- **Total: $410**

### Budget Setup:
- Behringer DCX2496: $200
- USB-MIDI adapter: $30
- **Total: $230**

---

## Advantages Over Software DSP (Raspberry Pi)

| Aspect | External DSP | Pi Software DSP |
|--------|--------------|-----------------|
| Audio Latency | <1ms ✅ | 7-16ms ❌ |
| Reliability | Hardware (bulletproof) ✅ | Software (can crash) ❌ |
| Failsafe | Keeps working if control fails ✅ | Audio stops if Pi crashes ❌ |
| Sound Quality | Professional grade ✅ | Good but not pro ❌ |
| DJ Override | Front panel control ✅ | Need to SSH into Pi ❌ |
| Venue Acceptance | Standard equipment ✅ | "Experimental" ❌ |
| Initial Cost | $200-400 | $150 (Pi + audio) |

---

## Next Steps

When ready to implement:

1. **Review this document** to confirm approach
2. **Decide**: Approach 1 (EQ) or Approach 2 (crossover)
   - Do you have separate subs? → Approach 2
   - Single full-range PA? → Approach 1
3. **Purchase DSP unit** (dbx DriveRack PA2 recommended)
4. **Test control protocol** (verify can send commands)
5. **Integrate with Bass Sentry** master node
6. **Test in non-critical environment**
7. **Deploy at event** with manual override capability

---

## References

- dbx DriveRack PA2 Manual: [dbxpro.com](https://dbxpro.com)
- Behringer DCX2496 Manual: [behringer.com](https://behringer.com)
- HiQnet Protocol Documentation: Available from dbx
- MIDI Implementation Chart: In DCX2496 manual Appendix

---

**Status**: Plan documented, not yet implemented
**Recommendation**: Start with dbx DriveRack PA2 + Approach 1 (EQ reduction)
**Estimated Implementation Time**: 1-2 days for integration + testing
