"""Tests for signal processors."""

import os
import pytest
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remote-node"))

from processors import (
    SignalProcessor,
    DAGProcessor,
    DbfsMeasurement,
    BandpassFilter,
    Resample,
    GridDecimationResample,
    MetadataTagger,
    REFERENCE_DBSPL,
)


class TestDbfsMeasurement:
    """Test dBFS measurement processor."""

    def test_silent_signal(self):
        """Test measurement of silent signal."""
        processor = DbfsMeasurement()
        data = {
            "data": [0] * 1000,
            "timestamp": 1000000000,
            "time_precision": "ns",
            "metadata": {"bit_depth": 16},
        }

        result = processor.process(data)

        assert result["data_type"] == "scalar"
        assert result["data"] == -np.inf

    def test_full_scale_signal(self):
        """Test measurement of full-scale signal."""
        processor = DbfsMeasurement()
        # Full scale for 16-bit is 32767
        data = {
            "data": [32767] * 1000,
            "timestamp": 1000000000,
            "time_precision": "ns",
            "metadata": {"bit_depth": 16},
        }

        result = processor.process(data)

        # Should be close to 0 dBFS + REFERENCE_DBSPL (120)
        assert result["data_type"] == "scalar"
        assert 119 < result["data"] < 121

    def test_rms_calculation(self):
        """Test RMS calculation."""
        # Known RMS: sine wave has RMS = amplitude / sqrt(2)
        t = np.linspace(0, 1, 44100)
        amplitude = 10000
        sine = (amplitude * np.sin(2 * np.pi * 100 * t)).astype(int).tolist()

        rms = DbfsMeasurement.rms(sine)
        expected_rms = amplitude / np.sqrt(2)

        assert abs(rms - expected_rms) < 100  # Within 1%

    def test_metadata_preserved(self):
        """Test that original metadata is preserved."""
        processor = DbfsMeasurement()
        data = {
            "data": [1000] * 100,
            "timestamp": 1234567890,
            "time_precision": "ns",
            "metadata": {"bit_depth": 16, "location": "stage", "custom": "value"},
        }

        result = processor.process(data)

        assert result["metadata"]["location"] == "stage"
        assert result["metadata"]["custom"] == "value"
        assert result["metadata"]["units"] == "dBSPL"

    def test_timestamp_preserved(self):
        """Test that timestamp is preserved."""
        processor = DbfsMeasurement()
        data = {
            "data": [1000] * 100,
            "timestamp": 9876543210,
            "time_precision": "ms",
            "metadata": {"bit_depth": 16},
        }

        result = processor.process(data)

        assert result["timestamp"] == 9876543210
        assert result["time_precision"] == "ms"


class TestBandpassFilter:
    """Test bandpass filter processor."""

    def test_filter_initialization(self):
        """Test filter initializes correctly."""
        filt = BandpassFilter(low_cut=100, high_cut=1000)
        assert filt.low_cut == 100
        assert filt.high_cut == 1000
        assert filt.sos is None  # Not initialized until process

    def test_filter_removes_dc(self):
        """Test filter removes DC component."""
        filt = BandpassFilter(low_cut=20, high_cut=200)

        # Signal with DC offset
        data = {"data": [1000] * 4410, "metadata": {"sample_rate": 44100}}

        result = filt.process(data)

        # DC should be heavily attenuated
        assert np.abs(np.mean(result["data"])) < 100

    def test_filter_passes_inband(self):
        """Test filter passes in-band frequencies."""
        filt = BandpassFilter(low_cut=50, high_cut=150)

        # 100Hz tone - should pass
        t = np.linspace(0, 0.5, 22050)
        tone = (10000 * np.sin(2 * np.pi * 100 * t)).tolist()

        data = {"data": tone, "metadata": {"sample_rate": 44100}}

        result = filt.process(data)

        # Should retain most energy (accounting for filter transients)
        input_power = np.mean(np.array(tone) ** 2)
        output_power = np.mean(np.array(result["data"]) ** 2)

        # First chunk has transients, so be lenient
        assert output_power > input_power * 0.3

    def test_filter_attenuates_out_of_band(self):
        """Test filter attenuates out-of-band frequencies."""
        filt = BandpassFilter(low_cut=100, high_cut=200)

        # 1000Hz tone - should be heavily attenuated
        t = np.linspace(0, 0.5, 22050)
        tone = (10000 * np.sin(2 * np.pi * 1000 * t)).tolist()

        data = {"data": tone, "metadata": {"sample_rate": 44100}}

        result = filt.process(data)

        # Out-of-band should be significantly attenuated
        input_power = np.mean(np.array(tone) ** 2)
        output_power = np.mean(np.array(result["data"]) ** 2)

        assert output_power < input_power * 0.1  # At least 10x reduction

    def test_filter_state_persistence(self):
        """Test filter maintains state across chunks."""
        filt = BandpassFilter(low_cut=50, high_cut=150)

        # Process two chunks
        chunk1 = {"data": [0] * 4410, "metadata": {"sample_rate": 44100}}
        chunk2 = {"data": [0] * 4410, "metadata": {"sample_rate": 44100}}

        filt.process(chunk1)
        assert filt.zi is not None

        zi_after_first = filt.zi.copy()

        filt.process(chunk2)

        # State should exist
        assert filt.zi is not None

    def test_filter_metadata_updated(self):
        """Test filter updates metadata."""
        filt = BandpassFilter(low_cut=35, high_cut=250, order=6)

        data = {"data": [0] * 1000, "metadata": {"sample_rate": 44100}}

        result = filt.process(data)

        assert result["metadata"]["filter_low"] == 35
        assert result["metadata"]["filter_high"] == 250
        assert result["metadata"]["filter_order"] == 6

    def test_invalid_low_cut_zero(self):
        """Test validation of low_cut at 0."""
        filt = BandpassFilter(low_cut=0, high_cut=100)
        with pytest.raises(ValueError, match="low_cut must be > 0"):
            filt.process({"data": [0] * 100, "metadata": {"sample_rate": 44100}})

    def test_invalid_high_cut_above_nyquist(self):
        """Test validation of high_cut above Nyquist."""
        filt = BandpassFilter(low_cut=100, high_cut=25000)
        with pytest.raises(ValueError, match="high_cut must be < Nyquist"):
            filt.process({"data": [0] * 100, "metadata": {"sample_rate": 44100}})

    def test_invalid_low_ge_high(self):
        """Test validation when low_cut >= high_cut."""
        filt = BandpassFilter(low_cut=200, high_cut=100)
        with pytest.raises(ValueError, match="low_cut.*must be < high_cut"):
            filt.process({"data": [0] * 100, "metadata": {"sample_rate": 44100}})


class TestMetadataTagger:
    """Test metadata tagger processor."""

    def test_add_tag(self):
        """Test adding a tag."""
        tagger = MetadataTagger(tag="reference")
        data = {"data": [1, 2, 3], "metadata": {}}

        result = tagger.process(data)

        assert "tags" in result["metadata"]
        assert "reference" in result["metadata"]["tags"]

    def test_append_to_existing_tags(self):
        """Test appending to existing tags."""
        tagger = MetadataTagger(tag="new_tag")
        data = {"data": [1, 2, 3], "metadata": {"tags": ["existing"]}}

        result = tagger.process(data)

        assert "existing" in result["metadata"]["tags"]
        assert "new_tag" in result["metadata"]["tags"]

    def test_preserves_data(self):
        """Test that data is preserved."""
        tagger = MetadataTagger(tag="test")
        data = {"data": [1, 2, 3], "metadata": {}}

        result = tagger.process(data)

        assert result["data"] == [1, 2, 3]


class TestResample:
    """Test resample processor."""

    def test_downsample(self):
        """Test downsampling."""
        resampler = Resample(new_sample_rate=22050)

        # 44100 Hz input
        data = {
            "data": list(range(44100)),
            "metadata": {"sample_rate": 44100},
        }

        result = resampler.process(data)

        # Should be roughly half the samples
        assert len(result["data"]) == 22050
        assert result["metadata"]["sample_rate"] == 22050

    def test_upsample(self):
        """Test upsampling."""
        resampler = Resample(new_sample_rate=88200)

        # 44100 Hz input
        data = {
            "data": list(range(44100)),
            "metadata": {"sample_rate": 44100},
        }

        result = resampler.process(data)

        # Should be roughly double the samples
        assert len(result["data"]) == 88200
        assert result["metadata"]["sample_rate"] == 88200


class TestGridDecimationResample:
    """Test grid-aligned decimation resampler."""

    def test_valid_frequency(self):
        """Test frequency validation."""
        # 1000 Hz -> 1,000,000 ns per sample (valid)
        assert GridDecimationResample.is_valid_frequency(1000) is True

        # 44100 Hz -> not an integer nanoseconds
        assert GridDecimationResample.is_valid_frequency(44100) is False

    def test_invalid_frequency_raises(self):
        """Test that invalid frequency raises error."""
        with pytest.raises(ValueError):
            GridDecimationResample(new_sample_rate=44100)

    def test_resample_to_grid(self):
        """Test resampling to grid-aligned rate."""
        resampler = GridDecimationResample(new_sample_rate=1000)

        # Create test data
        data = {
            "data": list(range(44100)),
            "timestamp": 1000000000,  # 1 second in ns
            "metadata": {"sample_rate": 44100},
        }

        result = resampler.process(data)

        assert result["metadata"]["sample_rate"] == 1000
        # Timestamp should be grid-aligned
        assert result["timestamp"] % 1000000 == 0  # Multiple of 1ms


class TestDAGProcessor:
    """Test DAG-based processor."""

    def test_simple_linear_dag(self):
        """Test simple linear DAG."""
        steps = {
            "start": {"type": "start", "next": ["1"]},
            "1": {"type": "metadata_tagger", "params": {"tag": "processed"}, "next": []},
        }
        step_map = {"start": None, "metadata_tagger": MetadataTagger}

        dag = DAGProcessor(steps, step_map)
        data = {"data": [1, 2, 3], "metadata": {}}

        result = dag.process(data)

        # DAG returns a list when there are next steps; single item when terminal
        if isinstance(result, list):
            assert len(result) == 1
            assert "processed" in result[0]["metadata"]["tags"]
        else:
            assert "processed" in result["metadata"]["tags"]

    def test_branching_dag(self):
        """Test DAG with branches."""
        steps = {
            "start": {"type": "start", "next": ["1", "2"]},
            "1": {"type": "metadata_tagger", "params": {"tag": "branch1"}, "next": []},
            "2": {"type": "metadata_tagger", "params": {"tag": "branch2"}, "next": []},
        }
        step_map = {"start": None, "metadata_tagger": MetadataTagger}

        dag = DAGProcessor(steps, step_map)
        data = {"data": [1, 2, 3], "metadata": {}}

        results = dag.process(data)

        # Should get results from both branches
        assert len(results) == 2
        tags = [r["metadata"]["tags"][0] for r in results]
        assert "branch1" in tags
        assert "branch2" in tags

    def test_unknown_step_logs_error(self):
        """Test that unknown step type logs error (caught in thread)."""
        steps = {
            "start": {"type": "start", "next": ["1"]},
            "1": {"type": "unknown_processor", "next": []},
        }
        step_map = {"start": None}

        dag = DAGProcessor(steps, step_map)

        # DAG catches exceptions in threads and logs them
        # So this should not raise, but return empty results
        result = dag.process({"data": [], "metadata": {}})
        assert result == []  # No successful results due to error

    def test_missing_step_logs_error(self):
        """Test that missing step logs error (caught in thread)."""
        steps = {
            "start": {"type": "start", "next": ["missing"]},
        }
        step_map = {"start": None}

        dag = DAGProcessor(steps, step_map)

        # DAG catches exceptions in threads and logs them
        result = dag.process({"data": [], "metadata": {}})
        assert result == []  # No successful results due to error


class TestSignalProcessor:
    """Test the SignalProcessor wrapper."""

    def test_empty_config(self):
        """Test with empty config."""
        processor = SignalProcessor({})

        # Should handle gracefully (empty steps)
        with pytest.raises((ValueError, KeyError)):
            processor.process({"data": [], "metadata": {}})

    def test_simple_config(self):
        """Test with simple config."""
        config = {
            "steps": {
                "start": {"type": "start", "next": ["1"]},
                "1": {
                    "type": "metadata_tagger",
                    "params": {"tag": "processed"},
                    "next": [],
                },
            }
        }

        processor = SignalProcessor(config)
        result = processor.process({"data": [1, 2, 3], "metadata": {}})

        assert isinstance(result, list)
        assert len(result) == 1
        assert "processed" in result[0]["metadata"]["tags"]

    def test_returns_list(self):
        """Test that process always returns a list."""
        config = {
            "steps": {
                "start": {"type": "start", "next": ["1"]},
                "1": {
                    "type": "metadata_tagger",
                    "params": {"tag": "test"},
                    "next": [],
                },
            }
        }

        processor = SignalProcessor(config)
        result = processor.process({"data": [], "metadata": {}})

        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
