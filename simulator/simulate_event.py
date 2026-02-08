#!/usr/bin/env python3
"""
Bass Sentry Event Simulator - PROOF IT WORKS!

This simulates a complete event with multiple remote nodes and proves:
1. Cross-correlation detects delays correctly
2. Physical distances are calculated accurately
3. System handles real-world noise and conditions
4. Visualization works as expected

Usage:
    python simulator/simulate_event.py --nodes 4 --duration 10 --output results/
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.signals import SignalGenerator, SignalConfig, SignalType

sys.path.insert(0, str(Path(__file__).parent.parent / "master-node"))
from correlation import ChunkToCCStream

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Physical constants
SPEED_OF_SOUND = 343.0  # meters per second (at 20°C)


@dataclass
class NodePosition:
    """Physical position of a node."""

    node_id: str
    x: float  # meters
    y: float  # meters
    z: float = 0.0  # meters (height)

    def distance_to(self, other: "NodePosition") -> float:
        """Calculate 3D distance to another node."""
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return np.sqrt(dx**2 + dy**2 + dz**2)


@dataclass
class SimulationConfig:
    """Configuration for event simulation."""

    # Event parameters
    duration: float = 10.0  # seconds
    sample_rate: int = 44100  # Hz
    chunk_duration: float = 0.5  # seconds
    chunk_rate: int = 2  # chunks per second

    # Audio parameters
    bass_frequency: float = 50.0  # Hz (main bass tone)
    signal_amplitude: float = 1.0
    noise_level_db: float = 10.0  # SNR in dB

    # Node positions (example venue layout)
    stage_position: NodePosition = None  # Reference node at stage
    remote_positions: List[NodePosition] = None  # Remote nodes in venue

    def __post_init__(self):
        """Set up default node positions if not provided."""
        if self.stage_position is None:
            # Reference node at stage
            self.stage_position = NodePosition("stage_ref", x=0, y=0, z=2.0)

        if self.remote_positions is None:
            # Example: 4 remote nodes in typical venue layout
            self.remote_positions = [
                NodePosition("dance_floor", x=10, y=5, z=1.5),  # ~11.2m from stage
                NodePosition("back_bar", x=20, y=10, z=1.5),  # ~22.4m from stage
                NodePosition("side_wall", x=5, y=15, z=1.5),  # ~15.8m from stage
                NodePosition("vip_area", x=15, y=20, z=2.0),  # ~25m from stage
            ]


class EventSimulator:
    """Simulates a complete Bass Sentry event."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.generator = SignalGenerator()
        self.correlator = ChunkToCCStream()

        # Results
        self.ground_truth_delays: Dict[str, float] = {}
        self.detected_delays: Dict[str, float] = {}
        self.correlation_peaks: Dict[str, np.ndarray] = {}
        self.distances: Dict[str, float] = {}

    def calculate_ground_truth(self):
        """Calculate expected delays based on physical positions."""
        logger.info("Calculating ground truth delays...")

        for remote_pos in self.config.remote_positions:
            # Physical distance
            distance = self.config.stage_position.distance_to(remote_pos)
            self.distances[remote_pos.node_id] = distance

            # Time delay (speed of sound)
            delay = distance / SPEED_OF_SOUND
            self.ground_truth_delays[remote_pos.node_id] = delay

            logger.info(
                f"{remote_pos.node_id}: {distance:.2f}m → {delay*1000:.1f}ms delay"
            )

    def generate_source_signal(self) -> np.ndarray:
        """Generate the source audio (what's playing at the stage)."""
        logger.info("Generating source signal...")

        # Use chirp for unambiguous correlation peak
        # Sweeps through bass frequencies (20-200 Hz)
        config = SignalConfig(
            signal_type=SignalType.CHIRP,
            duration=self.config.duration,
            sample_rate=self.config.sample_rate,
            start_frequency=20.0,
            end_frequency=200.0,
            amplitude=self.config.signal_amplitude,
        )

        return self.generator.generate(config)

    def generate_remote_signals(self, source: np.ndarray) -> Dict[str, np.ndarray]:
        """Generate what each remote node hears."""
        logger.info("Generating remote node signals...")

        remote_signals = {}

        for remote_pos in self.config.remote_positions:
            delay = self.ground_truth_delays[remote_pos.node_id]
            distance = self.distances[remote_pos.node_id]

            # Distance attenuation (inverse square law, simplified)
            attenuation = min(1.0, 10.0 / max(distance, 1.0))

            # Generate delayed, attenuated, noisy version
            # Use chirp for unambiguous correlation peak
            _, remote = self.generator.generate_reference_and_remote(
                source_config=SignalConfig(
                    signal_type=SignalType.CHIRP,
                    duration=self.config.duration,
                    sample_rate=self.config.sample_rate,
                    start_frequency=20.0,
                    end_frequency=200.0,
                    amplitude=self.config.signal_amplitude,
                ),
                delay_seconds=delay,
                signal_attenuation=attenuation,
                snr_db=self.config.noise_level_db,
            )

            remote_signals[remote_pos.node_id] = remote

            logger.info(
                f"{remote_pos.node_id}: delay={delay*1000:.1f}ms, attenuation={attenuation:.2f}"
            )

        return remote_signals

    def create_chunks(
        self, audio: np.ndarray, node_id: str, tags: List[str] = None
    ) -> List[Dict]:
        """Split audio into chunks like the real system."""
        chunk_size = int(self.config.sample_rate * self.config.chunk_duration)
        chunks = []

        for i in range(0, len(audio), chunk_size):
            chunk_data = audio[i : i + chunk_size]
            if len(chunk_data) == chunk_size:
                timestamp = int(1e9) + i * int(1e9 / self.config.sample_rate)
                chunk = {
                    "station_id": node_id,
                    "data_type": "audio_chunk",
                    "data": chunk_data.tolist(),
                    "timestamp": timestamp,
                    "time_precision": "ns",
                    "metadata": {
                        "sample_rate": self.config.sample_rate,
                        "bit_depth": 16,
                        "location": node_id,
                        "tags": tags or [],
                    },
                }
                chunks.append(chunk)

        return chunks

    def run_correlation(self, reference: np.ndarray, remotes: Dict[str, np.ndarray]):
        """Run cross-correlation like the real system."""
        logger.info("Running cross-correlation...")

        # Create chunks for reference
        ref_chunks = self.create_chunks(reference, "stage_ref", tags=["reference"])

        # Process reference chunks
        for chunk in ref_chunks:
            self.correlator.process(chunk)

        # Create and process remote chunks
        for node_id, remote_signal in remotes.items():
            remote_chunks = self.create_chunks(remote_signal, node_id)

            for chunk in remote_chunks:
                result = self.correlator.process(chunk)

        # Get final results
        if self.correlator.reference_stream is not None:
            ref_timestamps, ref_audio = self.correlator.reference_stream

            for remote_id, remote_stream in self.correlator.remote_streams.items():
                remote_timestamps, remote_audio = remote_stream

                # Align and correlate
                chunk_size = int(self.config.sample_rate * self.config.chunk_duration)
                ref_aligned, remote_aligned, quality = (
                    self.correlator._align_audio_with_gaps(
                        ref_timestamps,
                        ref_audio,
                        remote_timestamps,
                        remote_audio,
                        chunk_size,
                    )
                )

                if ref_aligned is not None and remote_aligned is not None:
                    db, tau, corr_coef = self.correlator.rcc(
                        ref_aligned, remote_aligned, self.config.sample_rate
                    )

                    self.detected_delays[remote_id] = tau

                    # Store full correlation for visualization
                    from scipy.signal import correlate

                    ref_norm = (ref_aligned - np.mean(ref_aligned)) / np.std(
                        ref_aligned
                    )
                    remote_norm = (remote_aligned - np.mean(remote_aligned)) / np.std(
                        remote_aligned
                    )
                    cc = correlate(remote_norm, ref_norm, mode="full", method="fft")
                    self.correlation_peaks[remote_id] = cc

                    logger.info(
                        f"{remote_id}: Detected {tau*1000:.1f}ms "
                        f"(expected {self.ground_truth_delays[remote_id]*1000:.1f}ms), "
                        f"error={abs(tau - self.ground_truth_delays[remote_id])*1000:.1f}ms"
                    )

    def calculate_detected_distances(self) -> Dict[str, float]:
        """Calculate distances from detected delays."""
        detected_distances = {}
        for node_id, delay in self.detected_delays.items():
            detected_distances[node_id] = delay * SPEED_OF_SOUND
        return detected_distances

    def generate_report(self, output_dir: Path):
        """Generate detailed report and visualizations."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Text report
        report_path = output_dir / "simulation_report.txt"
        with open(report_path, "w") as f:
            f.write("=" * 80 + "\n")
            f.write("BASS SENTRY SIMULATION REPORT\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"Configuration:\n")
            f.write(f"  Duration: {self.config.duration}s\n")
            f.write(f"  Sample Rate: {self.config.sample_rate} Hz\n")
            f.write(f"  Bass Frequency: {self.config.bass_frequency} Hz\n")
            f.write(f"  SNR: {self.config.noise_level_db} dB\n\n")

            f.write("Results:\n")
            f.write("-" * 80 + "\n")
            f.write(
                f"{'Node':<15} {'Distance (m)':<15} {'Delay (ms)':<15} "
                f"{'Detected (ms)':<15} {'Error (ms)':<15}\n"
            )
            f.write("-" * 80 + "\n")

            for node_id in self.ground_truth_delays:
                true_dist = self.distances[node_id]
                true_delay = self.ground_truth_delays[node_id]
                detected_delay = self.detected_delays.get(node_id, 0)
                error = abs(detected_delay - true_delay)

                f.write(
                    f"{node_id:<15} {true_dist:<15.2f} {true_delay*1000:<15.1f} "
                    f"{detected_delay*1000:<15.1f} {error*1000:<15.1f}\n"
                )

            f.write("-" * 80 + "\n")
            avg_error = np.mean(
                [
                    abs(self.detected_delays.get(nid, 0) - true_delay)
                    for nid, true_delay in self.ground_truth_delays.items()
                ]
            )
            f.write(f"\nAverage Error: {avg_error*1000:.2f} ms\n")
            f.write(
                f"Max Error: {max([abs(self.detected_delays.get(nid, 0) - true_delay) for nid, true_delay in self.ground_truth_delays.items()])*1000:.2f} ms\n\n"
            )

            # Accuracy assessment
            if avg_error < 0.001:  # < 1ms
                f.write("✅ EXCELLENT: Delay detection within 1ms!\n")
            elif avg_error < 0.005:  # < 5ms
                f.write("✅ GOOD: Delay detection within 5ms\n")
            elif avg_error < 0.010:  # < 10ms
                f.write("⚠️  ACCEPTABLE: Delay detection within 10ms\n")
            else:
                f.write("❌ POOR: Delay detection >10ms error\n")

        logger.info(f"Report saved to {report_path}")

        # Visualizations
        self.plot_venue_layout(output_dir)
        self.plot_correlation_peaks(output_dir)
        self.plot_distance_comparison(output_dir)

        logger.info(f"All results saved to {output_dir}")

    def plot_venue_layout(self, output_dir: Path):
        """Plot physical layout and detected positions."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

        # Left plot: Ground truth
        ax1.scatter(
            self.config.stage_position.x,
            self.config.stage_position.y,
            s=500,
            c="red",
            marker="*",
            label="Stage (Reference)",
            edgecolors="black",
            linewidths=2,
        )

        for pos in self.config.remote_positions:
            ax1.scatter(pos.x, pos.y, s=200, c="blue", marker="o", edgecolors="black")
            ax1.annotate(
                f"{pos.node_id}\n{self.distances[pos.node_id]:.1f}m",
                (pos.x, pos.y),
                xytext=(5, 5),
                textcoords="offset points",
            )
            # Draw line from stage
            ax1.plot(
                [self.config.stage_position.x, pos.x],
                [self.config.stage_position.y, pos.y],
                "k--",
                alpha=0.3,
            )

        ax1.set_xlabel("X (meters)")
        ax1.set_ylabel("Y (meters)")
        ax1.set_title("Ground Truth: Physical Layout")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.axis("equal")

        # Right plot: Detected positions
        detected_distances = self.calculate_detected_distances()

        ax2.scatter(
            self.config.stage_position.x,
            self.config.stage_position.y,
            s=500,
            c="red",
            marker="*",
            label="Stage (Reference)",
            edgecolors="black",
            linewidths=2,
        )

        for pos in self.config.remote_positions:
            detected_dist = detected_distances.get(pos.node_id, 0)
            error = abs(detected_dist - self.distances[pos.node_id])

            # Color code by error
            color = "green" if error < 0.5 else "orange" if error < 1.0 else "red"

            ax2.scatter(pos.x, pos.y, s=200, c=color, marker="o", edgecolors="black")
            ax2.annotate(
                f"{pos.node_id}\nDetected: {detected_dist:.1f}m\nError: {error:.2f}m",
                (pos.x, pos.y),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
            )

        ax2.set_xlabel("X (meters)")
        ax2.set_ylabel("Y (meters)")
        ax2.set_title("Detected Distances from Time Delays")
        ax2.grid(True, alpha=0.3)
        ax2.axis("equal")

        plt.tight_layout()
        plt.savefig(output_dir / "venue_layout.png", dpi=150)
        logger.info(f"Saved venue layout to {output_dir / 'venue_layout.png'}")
        plt.close()

    def plot_correlation_peaks(self, output_dir: Path):
        """Plot correlation functions showing peaks."""
        n_nodes = len(self.correlation_peaks)
        fig, axes = plt.subplots(n_nodes, 1, figsize=(12, 3 * n_nodes))

        if n_nodes == 1:
            axes = [axes]

        for ax, (node_id, cc) in zip(axes, self.correlation_peaks.items()):
            n = len(cc) // 2
            lags = np.arange(-n, n + 1 if len(cc) % 2 == 1 else n)
            time_lags = lags / self.config.sample_rate * 1000  # Convert to ms

            ax.plot(time_lags, cc, linewidth=0.5)

            # Mark peak
            peak_idx = np.argmax(np.abs(cc))
            peak_lag_ms = time_lags[peak_idx]
            ax.axvline(
                peak_lag_ms,
                color="r",
                linestyle="--",
                label=f"Peak: {peak_lag_ms:.1f}ms",
            )

            # Mark expected
            expected_ms = self.ground_truth_delays[node_id] * 1000
            ax.axvline(
                expected_ms,
                color="g",
                linestyle="--",
                label=f"Expected: {expected_ms:.1f}ms",
            )

            ax.set_xlabel("Time Lag (ms)")
            ax.set_ylabel("Correlation")
            ax.set_title(f"{node_id} - Cross-Correlation Function")
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Zoom in around peak
            ax.set_xlim(
                [
                    max(time_lags[0], expected_ms - 50),
                    min(time_lags[-1], expected_ms + 50),
                ]
            )

        plt.tight_layout()
        plt.savefig(output_dir / "correlation_peaks.png", dpi=150)
        logger.info(
            f"Saved correlation peaks to {output_dir / 'correlation_peaks.png'}"
        )
        plt.close()

    def plot_distance_comparison(self, output_dir: Path):
        """Bar chart comparing true vs detected distances."""
        node_ids = list(self.distances.keys())
        true_distances = [self.distances[nid] for nid in node_ids]
        detected_distances = [
            self.calculate_detected_distances().get(nid, 0) for nid in node_ids
        ]

        x = np.arange(len(node_ids))
        width = 0.35

        fig, ax = plt.subplots(figsize=(12, 6))
        bars1 = ax.bar(
            x - width / 2,
            true_distances,
            width,
            label="Ground Truth",
            color="blue",
            alpha=0.7,
        )
        bars2 = ax.bar(
            x + width / 2,
            detected_distances,
            width,
            label="Detected",
            color="green",
            alpha=0.7,
        )

        ax.set_xlabel("Node")
        ax.set_ylabel("Distance (meters)")
        ax.set_title("Distance Detection Accuracy")
        ax.set_xticks(x)
        ax.set_xticklabels(node_ids, rotation=45, ha="right")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")

        # Add value labels on bars
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{height:.1f}m",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )

        plt.tight_layout()
        plt.savefig(output_dir / "distance_comparison.png", dpi=150)
        logger.info(
            f"Saved distance comparison to {output_dir / 'distance_comparison.png'}"
        )
        plt.close()

    def run(self, output_dir: Path):
        """Run complete simulation."""
        logger.info("=" * 80)
        logger.info("STARTING BASS SENTRY EVENT SIMULATION")
        logger.info("=" * 80)

        # Step 1: Calculate ground truth
        self.calculate_ground_truth()

        # Step 2: Generate signals
        source = self.generate_source_signal()
        remotes = self.generate_remote_signals(source)

        # Step 3: Run correlation
        self.run_correlation(source, remotes)

        # Step 4: Generate report and visualizations
        self.generate_report(output_dir)

        logger.info("=" * 80)
        logger.info("SIMULATION COMPLETE!")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Simulate Bass Sentry event and prove it works"
    )
    parser.add_argument(
        "--duration", type=float, default=10.0, help="Simulation duration in seconds"
    )
    parser.add_argument(
        "--snr", type=float, default=10.0, help="Signal-to-noise ratio in dB"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="simulator/results",
        help="Output directory for results",
    )
    parser.add_argument(
        "--frequency", type=float, default=50.0, help="Bass frequency in Hz"
    )

    args = parser.parse_args()

    # Create config
    config = SimulationConfig(
        duration=args.duration,
        bass_frequency=args.frequency,
        noise_level_db=args.snr,
    )

    # Run simulation
    simulator = EventSimulator(config)
    simulator.run(Path(args.output))


if __name__ == "__main__":
    main()
