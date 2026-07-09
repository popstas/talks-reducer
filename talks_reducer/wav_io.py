"""Minimal WAV reader/writer used to avoid a SciPy dependency in the bundle.

The pipeline only needs two WAV shapes: reading the 16-bit PCM audio that FFmpeg
extracts and writing the normalised floating-point result. SciPy's
``scipy.io.wavfile`` handles both, but pulling in SciPy adds ~75 MB to the frozen
distribution while every other SciPy feature goes unused. This module implements
just enough of the RIFF/WAVE container to be a drop-in replacement for the
``read``/``write`` helpers the pipeline calls, matching SciPy's return types
(interleaved ``numpy`` arrays, mono collapsed to 1-D) and byte layout.
"""

from __future__ import annotations

import struct
from typing import BinaryIO, Tuple

import numpy as np

__all__ = ["read", "write"]

_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


def _dtype_for_pcm(bits_per_sample: int) -> np.dtype:
    """Return the ``numpy`` dtype SciPy uses for integer PCM samples."""

    if bits_per_sample == 8:
        return np.dtype("uint8")  # 8-bit WAV audio is unsigned per the spec.
    if bits_per_sample == 16:
        return np.dtype("<i2")
    if bits_per_sample == 32:
        return np.dtype("<i4")
    if bits_per_sample == 64:
        return np.dtype("<i8")
    raise ValueError(f"Unsupported PCM bit depth: {bits_per_sample}")


def _dtype_for_float(bits_per_sample: int) -> np.dtype:
    """Return the ``numpy`` dtype for IEEE floating-point samples."""

    if bits_per_sample == 32:
        return np.dtype("<f4")
    if bits_per_sample == 64:
        return np.dtype("<f8")
    raise ValueError(f"Unsupported IEEE float bit depth: {bits_per_sample}")


def _read_chunk_header(stream: BinaryIO) -> Tuple[bytes, int]:
    """Read a RIFF sub-chunk identifier and its declared byte length."""

    header = stream.read(8)
    if len(header) < 8:
        return b"", 0
    chunk_id = header[:4]
    (size,) = struct.unpack("<I", header[4:8])
    return chunk_id, size


def read(filename: str) -> Tuple[int, np.ndarray]:
    """Read a PCM or IEEE-float WAV file into ``(sample_rate, data)``.

    Mono files return a 1-D array and multi-channel files return a
    ``(frames, channels)`` array, mirroring ``scipy.io.wavfile.read``.
    """

    with open(filename, "rb") as stream:
        riff = stream.read(12)
        if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
            raise ValueError(f"Not a WAV file: {filename!r}")

        fmt_tag = None
        channels = 1
        sample_rate = 0
        bits_per_sample = 0
        data_bytes = b""

        while True:
            chunk_id, size = _read_chunk_header(stream)
            if not chunk_id:
                break

            if chunk_id == b"fmt ":
                fmt_body = stream.read(size)
                (
                    fmt_tag,
                    channels,
                    sample_rate,
                    _byte_rate,
                    _block_align,
                    bits_per_sample,
                ) = struct.unpack("<HHIIHH", fmt_body[:16])
                if fmt_tag == _WAVE_FORMAT_EXTENSIBLE and len(fmt_body) >= 26:
                    # The real format lives in the first two bytes of the GUID.
                    (fmt_tag,) = struct.unpack("<H", fmt_body[24:26])
            elif chunk_id == b"data":
                data_bytes = stream.read(size)
            else:
                stream.seek(size, 1)

            if size % 2 == 1:
                stream.seek(1, 1)  # Chunks are word-aligned with a pad byte.

        if fmt_tag is None:
            raise ValueError(f"WAV file missing 'fmt ' chunk: {filename!r}")

        if fmt_tag == _WAVE_FORMAT_PCM:
            dtype = _dtype_for_pcm(bits_per_sample)
        elif fmt_tag == _WAVE_FORMAT_IEEE_FLOAT:
            dtype = _dtype_for_float(bits_per_sample)
        else:
            raise ValueError(f"Unsupported WAV format tag: {fmt_tag}")

        samples = np.frombuffer(data_bytes, dtype=dtype)
        if channels > 1:
            samples = samples.reshape(-1, channels)

        return sample_rate, samples


def write(filename: str, rate: int, data: np.ndarray) -> None:
    """Write ``data`` as a WAV file, matching ``scipy.io.wavfile.write``.

    Integer dtypes are stored as PCM and floating-point dtypes as IEEE float, so
    the normalised float output of the pipeline is preserved bit-for-bit.
    """

    array = np.asarray(data)
    if array.dtype.kind == "f":
        fmt_tag = _WAVE_FORMAT_IEEE_FLOAT
    elif array.dtype.kind in ("i", "u"):
        fmt_tag = _WAVE_FORMAT_PCM
    else:
        raise ValueError(f"Unsupported sample dtype: {array.dtype}")

    # Store samples little-endian and interleaved, as the WAV container expects.
    array = np.ascontiguousarray(array.astype(array.dtype.newbyteorder("<")))

    channels = array.shape[1] if array.ndim == 2 else 1
    frames = array.shape[0] if array.size else 0
    bits_per_sample = array.dtype.itemsize * 8
    block_align = channels * array.dtype.itemsize
    byte_rate = rate * block_align

    payload = array.tobytes()
    fmt_chunk = struct.pack(
        "<HHIIHH",
        fmt_tag,
        channels,
        int(rate),
        byte_rate,
        block_align,
        bits_per_sample,
    )
    if fmt_tag != _WAVE_FORMAT_PCM:
        # Non-PCM formats carry a cbSize field and a 'fact' chunk, matching how
        # ``scipy.io.wavfile`` serialises IEEE float audio.
        fmt_chunk += struct.pack("<H", 0)

    with open(filename, "wb") as stream:
        data_size = len(payload)
        riff_size = 4 + (8 + len(fmt_chunk)) + (8 + data_size)
        if fmt_tag != _WAVE_FORMAT_PCM:
            riff_size += 8 + 4  # 'fact' chunk header plus its 4-byte body.
        stream.write(b"RIFF")
        stream.write(struct.pack("<I", riff_size))
        stream.write(b"WAVE")
        stream.write(b"fmt ")
        stream.write(struct.pack("<I", len(fmt_chunk)))
        stream.write(fmt_chunk)
        if fmt_tag != _WAVE_FORMAT_PCM:
            stream.write(b"fact")
            stream.write(struct.pack("<I", 4))
            stream.write(struct.pack("<I", frames))
        stream.write(b"data")
        stream.write(struct.pack("<I", data_size))
        stream.write(payload)
        if data_size % 2 == 1:
            stream.write(b"\x00")
