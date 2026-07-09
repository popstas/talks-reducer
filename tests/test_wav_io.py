"""Verify the bundled WAV helper matches ``scipy.io.wavfile`` for our formats."""

import numpy as np
import pytest

from talks_reducer import wav_io

scipy_wavfile = pytest.importorskip("scipy.io.wavfile")


@pytest.mark.parametrize(
    "data",
    [
        (np.random.default_rng(0).standard_normal((500, 2)) * 3000).astype(np.int16),
        (np.random.default_rng(1).standard_normal(500) * 3000).astype(np.int16),
        np.random.default_rng(2).standard_normal((500, 2)).astype(np.float64),
        np.random.default_rng(3).standard_normal((500, 2)).astype(np.float32),
        (np.random.default_rng(4).integers(0, 256, (300, 2))).astype(np.uint8),
        (np.random.default_rng(5).standard_normal((300, 2)) * 1e6).astype(np.int32),
    ],
)
def test_write_matches_scipy_bytes(tmp_path, data):
    """Our writer must produce byte-identical files to SciPy's writer."""

    ours = tmp_path / "ours.wav"
    theirs = tmp_path / "theirs.wav"
    wav_io.write(str(ours), 44100, data)
    scipy_wavfile.write(str(theirs), 44100, data)

    assert ours.read_bytes() == theirs.read_bytes()


@pytest.mark.parametrize(
    "data",
    [
        (np.random.default_rng(10).standard_normal((500, 2)) * 3000).astype(np.int16),
        (np.random.default_rng(11).standard_normal(500) * 3000).astype(np.int16),
        np.random.default_rng(12).standard_normal((500, 2)).astype(np.float64),
        np.random.default_rng(13).standard_normal((500, 2)).astype(np.float32),
    ],
)
def test_read_matches_scipy(tmp_path, data):
    """Reading a SciPy-written file must yield the same rate, dtype, and values."""

    path = tmp_path / "sample.wav"
    scipy_wavfile.write(str(path), 32000, data)

    scipy_rate, scipy_data = scipy_wavfile.read(str(path))
    our_rate, our_data = wav_io.read(str(path))

    assert our_rate == scipy_rate
    assert our_data.dtype == scipy_data.dtype
    assert our_data.shape == scipy_data.shape
    np.testing.assert_array_equal(our_data, scipy_data)


def test_round_trip_float64(tmp_path):
    """A float round-trip must return the original samples unchanged."""

    data = np.random.default_rng(20).standard_normal((256, 2)).astype(np.float64)
    path = tmp_path / "rt.wav"
    wav_io.write(str(path), 48000, data)
    rate, restored = wav_io.read(str(path))

    assert rate == 48000
    np.testing.assert_array_equal(restored, data)
