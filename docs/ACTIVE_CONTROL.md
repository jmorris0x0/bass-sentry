# Active Bass Control - Automatic Limiting

**Goal**: Automatically limit bass levels based on remote measurements, bypassing DJ control.

---

## System Architecture

### Current (Monitoring Only)
```
DJ Mixer → PA System → Venue
              ↓
         Remote Nodes → Master → Grafana
                                    ↓
                                   DJ (ignores it!)
```

### Active Control
```
DJ Mixer → Bass Limiter/Controller → PA System → Venue
              ↑                                     ↓
              └─────── Master Node ←──── Remote Nodes
                       (control loop)
```

---

## What You Need

### 1. Audio Signal Insertion Point

**Option A: Digital Signal Path (Best)**
```
DJ Mixer (digital) → Raspberry Pi / PC → DSP → PA System
                     ↑ USB Audio Interface
                     └─ Bass Sentry Control
```

**Option B: Analog Signal Path**
```
DJ Mixer (analog) → USB Audio Interface → PC with DSP → Audio Interface → PA System
                                          ↑
                                    Bass Sentry Control
```

**Option C: External DSP Unit (Easiest Integration)**
```
DJ Mixer → DSP Processor (controlled via OSC/MIDI) → PA System
              ↑
         Bass Sentry Control (sends commands)
```

### 2. Hardware Requirements

#### Option A: All-in-One Pi Solution
- **Raspberry Pi 4** (8GB RAM recommended)
- **Professional USB Audio Interface** (low latency)
  - Focusrite Scarlett 2i2 ($170)
  - Behringer UMC204HD ($80)
  - MOTU M2 ($200)
- **Latency**: 5-10ms (acceptable for bass control)

#### Option B: Dedicated DSP Computer
- **Linux PC** with real-time kernel
- **Pro audio interface** (class-compliant, JACK support)
  - RME Babyface Pro ($700) - ultra-low latency
  - Focusrite Clarett+ ($300) - good latency
- **Latency**: 2-5ms (excellent)

#### Option C: Hardware DSP (Recommended for Production)
**Commercial DSP Units**:
- **dbx DriveRack PA2** ($400)
  - Built-in limiters, EQ, crossovers
  - RS-232 or Ethernet control
  - Used in many venues already

- **Behringer DCX2496** ($200)
  - Digital crossover/EQ/limiter
  - MIDI control
  - Budget option

- **Symetrix Jupiter** ($2000+)
  - Professional DSP platform
  - Dante network audio
  - Full automation capability

**Pros**: Low latency, reliable, built for live sound
**Cons**: Need control protocol integration

---

## Software Components

### 1. Real-Time Audio Processing

**Framework**: JACK Audio Connection Kit (Linux)
```bash
# Install JACK
sudo apt-get install jackd2 qjackctl

# Low-latency kernel for Pi
sudo apt-get install linux-lowlatency
```

**Python DSP**: Use `python-sounddevice` with JACK
```python
import sounddevice as sd
import numpy as np
from scipy import signal

class RealtimeBassLimiter:
    def __init__(self, sample_rate=48000, block_size=128):
        self.sample_rate = sample_rate
        self.block_size = block_size

        # Bass filter (20-120 Hz)
        self.bass_filter = signal.butter(
            4, [20, 120], btype='band',
            fs=sample_rate, output='sos'
        )

        # Target dBFS at remote locations
        self.target_bass_level = -20  # dBFS
        self.max_bass_level = -15     # Hard limit

        # Smoothing for gain changes (avoid clicking)
        self.current_gain = 1.0
        self.gain_smooth_time = 0.1  # 100ms

    def callback(self, indata, outdata, frames, time, status):
        """Process audio in real-time."""
        if status:
            print(status)

        # Get current remote measurements
        remote_bass_level = self.get_remote_bass_level()

        # Calculate required gain reduction
        target_gain = self.calculate_gain_reduction(remote_bass_level)

        # Smooth gain changes to avoid clicks
        self.current_gain = self.smooth_gain(self.current_gain, target_gain)

        # Apply gain
        outdata[:] = indata * self.current_gain

    def get_remote_bass_level(self):
        """Query latest bass level from remote nodes (via Redis/shared memory)."""
        # This needs to be FAST (microseconds)
        # Don't query InfluxDB here - too slow!
        return self.shared_state.get('max_bass_level', -30)

    def calculate_gain_reduction(self, current_level):
        """Calculate gain to bring bass to target level."""
        if current_level > self.max_bass_level:
            # Hard limit: reduce gain immediately
            excess_db = current_level - self.max_bass_level
            gain_reduction_db = -excess_db
            return 10 ** (gain_reduction_db / 20)

        elif current_level > self.target_bass_level:
            # Soft limit: gentle reduction
            excess_db = current_level - self.target_bass_level
            gain_reduction_db = -excess_db * 0.5  # Gentler slope
            return 10 ** (gain_reduction_db / 20)

        else:
            # Below target: no reduction
            return 1.0

    def smooth_gain(self, current, target):
        """Exponential smoothing to avoid clicks."""
        alpha = 1.0 - np.exp(-self.block_size / (self.gain_smooth_time * self.sample_rate))
        return current + alpha * (target - current)
```

### 2. Low-Latency Communication

**Problem**: MQTT is too slow for control (500ms+ latency)

**Solution**: Use Redis for sub-millisecond communication
```python
import redis

# Master node publishes measurements to Redis
r = redis.Redis(host='localhost', port=6379)

# Every correlation result:
r.set(f'bass_level:{node_id}', bass_level_db)
r.set('max_bass_level', max(all_bass_levels))  # Maximum across all nodes

# DSP reads from Redis in callback (microseconds)
max_level = float(r.get('max_bass_level'))
```

**Latency**: <1ms for Redis read

### 3. Control Algorithm

**Simple Version**: Direct gain control
```python
if remote_bass > threshold:
    reduce_gain()
else:
    restore_gain()
```

**Better Version**: PID Controller
```python
class BassController:
    """PID controller for smooth bass limiting."""

    def __init__(self, setpoint=-20, Kp=0.5, Ki=0.1, Kd=0.05):
        self.setpoint = setpoint  # Target dB level
        self.Kp = Kp  # Proportional gain
        self.Ki = Ki  # Integral gain
        self.Kd = Kd  # Derivative gain

        self.integral = 0
        self.last_error = 0

    def update(self, measured_level, dt):
        """Calculate control output (gain adjustment)."""
        error = self.setpoint - measured_level

        # Proportional
        P = self.Kp * error

        # Integral (accumulated error)
        self.integral += error * dt
        I = self.Ki * self.integral

        # Derivative (rate of change)
        D = self.Kd * (error - self.last_error) / dt
        self.last_error = error

        # Control output
        gain_db = P + I + D

        # Clamp to reasonable range
        gain_db = np.clip(gain_db, -30, 0)  # Max 30dB reduction, no boost

        return 10 ** (gain_db / 20)  # Convert to linear gain
```

**Advanced Version**: Multi-band control
```python
class MultibandBassController:
    """Control different bass frequencies independently."""

    def __init__(self):
        # Three bass bands
        self.bands = {
            'sub_bass': (20, 60),      # Sub-bass
            'mid_bass': (60, 120),     # Mid-bass
            'upper_bass': (120, 250)   # Upper bass
        }

        self.controllers = {
            band: BassController(setpoint=target)
            for band, target in [
                ('sub_bass', -25),      # Strictest (most annoying)
                ('mid_bass', -20),      # Moderate
                ('upper_bass', -15)     # Gentler
            ]
        }
```

---

## Integration Approaches

### Approach 1: Software DSP (Full Control)

**Components**:
1. Raspberry Pi 4 running real-time Linux
2. USB audio interface (in/out)
3. JACK audio server
4. Python DSP with bass limiter
5. Bass Sentry master node

**Data Flow**:
```
DJ Mixer → USB In → JACK → Bass Limiter → JACK → USB Out → PA
                            ↑
                       Bass Sentry
                       (Redis pub/sub)
```

**Code Structure**:
```python
# bass_limiter.py
import sounddevice as sd
import redis
from bass_controller import BassController

# Connect to Redis (fast communication)
r = redis.Redis()

# Create controller
controller = BassController(setpoint=-20)

def audio_callback(indata, outdata, frames, time, status):
    # Get latest remote measurement (sub-millisecond)
    max_bass = float(r.get('max_bass_level') or -30)

    # Calculate gain
    gain = controller.update(max_bass, dt=frames/sample_rate)

    # Apply gain
    outdata[:] = indata * gain

# Start audio stream
stream = sd.Stream(
    samplerate=48000,
    blocksize=128,  # Low latency
    channels=2,
    callback=audio_callback
)
stream.start()
```

**Pros**:
- ✅ Full control over algorithm
- ✅ Can add custom features
- ✅ Cheap hardware
- ✅ Easy to modify

**Cons**:
- ❌ Requires audio routing setup
- ❌ Potential for audio glitches
- ❌ DJ might bypass it

**Latency**: 5-15ms (acceptable for bass)

---

### Approach 2: External DSP Control (Production-Ready)

**Hardware**: dbx DriveRack PA2 ($400)

**Control**: Via Ethernet or RS-232
```python
# control_driverack.py
import socket

class DriveRackController:
    """Control dbx DriveRack via Ethernet."""

    def __init__(self, ip='192.168.1.100', port=3804):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ip, port))

    def set_bass_limit(self, freq_band, threshold_db):
        """Set limiter threshold for bass band."""
        # DriveRack protocol (check manual for exact format)
        cmd = f"SET LIMITER BAND{freq_band} THRESHOLD {threshold_db}\r\n"
        self.sock.send(cmd.encode())

    def set_eq_gain(self, band, gain_db):
        """Adjust EQ gain for bass band."""
        cmd = f"SET EQ BAND{band} GAIN {gain_db}\r\n"
        self.sock.send(cmd.encode())

# Control loop
driverack = DriveRackController()

while True:
    # Get remote bass level
    bass_level = get_remote_bass_level()

    # Calculate required reduction
    if bass_level > -15:
        # Reduce bass by excess amount
        reduction = -15 - bass_level
        driverack.set_eq_gain(band=1, gain_db=reduction)

    time.sleep(0.1)  # 100ms update rate
```

**Alternative**: MIDI Control (Behringer DCX2496)
```python
import mido

# Open MIDI port
outport = mido.open_output('DCX2496')

# Send program change (switch to "bass limited" preset)
outport.send(mido.Message('program_change', program=5))

# Or send CC messages for continuous control
# (check DCX2496 MIDI implementation)
outport.send(mido.Message('control_change', control=20, value=64))
```

**Pros**:
- ✅ Professional hardware
- ✅ Reliable, low latency
- ✅ Used in many venues already
- ✅ DJ can't bypass easily
- ✅ No audio glitches

**Cons**:
- ❌ Need to buy hardware
- ❌ Less flexible than software
- ❌ Need to learn control protocol

**Latency**: <1ms for DSP, 50-100ms for control updates (fine)

---

### Approach 3: Hybrid (Monitor + Software Limiter)

**Setup**:
```
DJ Mixer ──┬──→ PA System (direct, for safety)
           │
           └──→ Pi + Limiter ──→ Secondary PA / Subs only
                    ↑
              Bass Sentry Control
```

**Concept**:
- Main PA gets full signal (failsafe)
- Bass Sentry controls ONLY the subwoofers
- If system fails, mains still work

**Pros**:
- ✅ Failsafe (main system always works)
- ✅ Only limits problematic frequencies
- ✅ Easier to get DJ/venue buy-in

**Cons**:
- ❌ More complex routing
- ❌ Need separate amp for subs

---

## Control Strategies

### Strategy 1: Hard Limit (Simple)
```python
def hard_limit(measured_bass, threshold=-15):
    """Immediate gain reduction when over threshold."""
    if measured_bass > threshold:
        excess = measured_bass - threshold
        return 10 ** (-excess / 20)  # Reduce by exact excess
    return 1.0  # No reduction
```

**Pros**: Simple, effective
**Cons**: Can sound abrupt, "pumping" effect

---

### Strategy 2: Soft Knee Compression
```python
def soft_knee_limiter(measured_bass, threshold=-20, knee=5):
    """Gentle compression above threshold."""
    if measured_bass < (threshold - knee/2):
        return 1.0  # No reduction
    elif measured_bass > (threshold + knee/2):
        # Above knee: hard limiting
        excess = measured_bass - threshold
        return 10 ** (-excess / 20)
    else:
        # In knee: gradual compression
        x = (measured_bass - threshold + knee/2) / knee
        ratio = 1 + x * 9  # 1:1 to 10:1 ratio
        excess = (measured_bass - threshold) * (ratio - 1) / ratio
        return 10 ** (-excess / 20)
```

**Pros**: Smoother, more musical
**Cons**: More complex

---

### Strategy 3: Multi-Location Control
```python
def multi_location_control(node_measurements, priorities):
    """
    Control based on multiple locations.

    Priorities:
    - 'max': Control to worst location (most conservative)
    - 'weighted': Weight by importance (e.g., neighbors > dance floor)
    - 'percentile': Control to 90th percentile
    """
    if priorities == 'max':
        return max(node_measurements.values())

    elif priorities == 'weighted':
        weights = {
            'neighbor_north': 2.0,  # Most important
            'neighbor_south': 2.0,
            'dance_floor': 0.5,     # Less important
            'vip': 0.3
        }
        weighted_sum = sum(
            measurements[node] * weights.get(node, 1.0)
            for node in measurements
        )
        return weighted_sum / sum(weights.values())

    elif priorities == 'percentile':
        values = sorted(node_measurements.values())
        idx = int(len(values) * 0.9)  # 90th percentile
        return values[idx]
```

---

## Safety Considerations

### 1. Failsafe Modes

```python
class SafetyMonitor:
    """Monitor system health and fail gracefully."""

    def __init__(self):
        self.last_measurement_time = {}
        self.timeout = 5.0  # seconds

    def check_health(self):
        """Verify system is working."""
        now = time.time()

        # Check if we're getting measurements
        for node_id, last_time in self.last_measurement_time.items():
            if now - last_time > self.timeout:
                logger.error(f"Node {node_id} timeout!")
                return False

        # Check if Redis is responding
        try:
            r.ping()
        except:
            logger.error("Redis connection lost!")
            return False

        return True

    def failsafe_mode(self):
        """What to do if system fails."""
        logger.critical("Entering failsafe mode - disabling limiting")

        # Option 1: Bypass (pass through)
        set_gain(1.0)

        # Option 2: Gentle limiting (conservative)
        set_gentle_limit(-10)  # Only limit extreme levels

        # Option 3: Switch to backup preset
        dsp.load_preset('safe_backup')
```

### 2. Gradual Changes
```python
# Never change gain instantly - always ramp
def ramp_gain(current_gain, target_gain, duration=0.5):
    """Ramp gain over duration to avoid clicks."""
    steps = int(duration * sample_rate / block_size)
    gain_step = (target_gain - current_gain) / steps

    for i in range(steps):
        yield current_gain + gain_step * i
```

### 3. Override Capability
```python
# DJ can temporarily override (15 minutes)
def dj_override():
    """Allow DJ to disable limiting temporarily."""
    override_until = time.time() + 15 * 60  # 15 minutes
    logger.warning("DJ override activated for 15 minutes")

    while time.time() < override_until:
        yield 1.0  # No limiting

    logger.info("Override expired, resuming automatic control")
```

---

## Recommended Starting Point

### Phase 1: Proof of Concept (Cheap & Quick)
**Hardware**:
- Raspberry Pi 4 (8GB): $75
- Behringer UMC204HD: $80
- Cables: $20
**Total**: ~$175

**Software**:
- JACK audio server
- Python with `sounddevice`
- Redis for fast communication
- Simple hard limiter

**Test**: Run in parallel with existing system, log what it *would* do

---

### Phase 2: Production (Recommended)
**Hardware**:
- dbx DriveRack PA2: $400
- Ethernet cable: $10

**Software**:
- Bass Sentry master node (existing)
- DriveRack control script (50 lines of Python)
- Redis for fast data sharing

**Integration**:
```
DJ → DriveRack (EQ + Limiter) → PA
        ↑
   Ethernet Control
        ↑
   Bass Sentry Master
        ↑
   Remote Nodes (MQTT)
```

---

## Code Examples

I'll create a complete working example in the next response showing:
1. Real-time bass limiter
2. Redis integration
3. Control loop
4. Safety mechanisms

Would you like me to build:
- **A) Software solution** (Pi + USB audio)
- **B) Hardware DSP control** (DriveRack/Behringer)
- **C) Both** (for comparison)

Also, what's your budget and existing equipment?
