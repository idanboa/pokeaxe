"""Pokémon cries as Golden Axe DAC sample blocks.

The Z80 sound driver plays one sample from Z80 RAM $0F08 using Sega's 4-bit DPCM (two nibbles per
byte, each an index into the delta table at Z80 $0DE8). The 68000 copies a 2512-byte block (8-byte
header + data) to Z80 $0F00 before each play; header: data length (LE word), $0008, $0800, pitch, $80.
"""
import subprocess
import imageio_ffmpeg

BLOCK = 0x9D0                      # bytes copied by the loader at $35BC
MAX_DATA = BLOCK - 8
DELTAS = [0, 1, 2, 4, 8, 16, 32, 64, -128, -1, -2, -4, -8, -16, -32, -64]


def rate(pitch, cal):
    """Playback rate in Hz for a pitch byte (the driver's delay-loop count), from calibration."""
    return cal['clock'] / (cal['base'] + cal['per'] * pitch)


def load(path, sr):
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-loglevel', 'error', '-i', path, '-ac', '1', '-ar', str(int(sr)),
                          '-f', 's16le', '-'], capture_output=True, check=True).stdout
    return [int.from_bytes(raw[i:i + 2], 'little', signed=True) / 32768 for i in range(0, len(raw), 2)]


def dpcm(samples):
    """Greedy 4-bit DPCM encode of floats in [-1, 1]; no wrap-around."""
    acc, nibbles = 0x80, []
    for x in samples:
        target = max(0, min(255, round(128 + 127 * x)))
        best = min(range(16), key=lambda i: abs(target - (acc + DELTAS[i])) if 0 <= acc + DELTAS[i] <= 255 else 999)
        acc += DELTAS[best]
        nibbles.append(best)
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def block(samples, pitch):
    data = dpcm(samples)[:MAX_DATA]
    head = len(data).to_bytes(2, 'little') + bytes([0x00, 0x08, 0x08, 0x00, pitch, 0x80])
    return (head + data).ljust(BLOCK, b'\x88')     # pad with zero-delta nibbles... 0x88 = -128 pairs cancel


def cry(path, pitch, cal, gain=0.95, speed=1.0):
    """Cry block: resampled to the driver rate for `pitch`, trimmed, normalised, fitted to the buffer."""
    sr = rate(pitch, cal)
    s = load(path, sr * speed)
    # trim leading/trailing near-silence
    thr = 0.02
    i = next((k for k, v in enumerate(s) if abs(v) > thr), 0)
    j = len(s) - next((k for k, v in enumerate(reversed(s)) if abs(v) > thr), 0)
    s = s[i:j]
    peak = max(abs(v) for v in s) or 1
    s = [v * gain / peak for v in s]
    n = MAX_DATA * 2
    if len(s) > n:                 # fade out what fits
        s = s[:n]
        for k in range(200):
            s[n - 1 - k] *= k / 200
    return block(s, pitch), len(s) / sr
