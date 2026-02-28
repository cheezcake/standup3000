#!/usr/bin/env python3
"""Generate placeholder sound effects for Standup 3000.

Creates simple synthesized MP3-compatible WAV sounds in static/sounds/.
These are functional placeholders — replace with real sounds for production.

Usage: python generate_sounds.py
"""
import struct
import math
import os

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "static", "sounds")


def write_wav(filename, samples, sample_rate=44100):
    """Write 16-bit mono WAV file."""
    path = os.path.join(SOUNDS_DIR, filename)
    n = len(samples)
    data = struct.pack(f"<{n}h", *[max(-32768, min(32767, int(s))) for s in samples])

    with open(path, "wb") as f:
        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)
    print(f"  Created {filename} ({len(data)} bytes)")


def sine(freq, duration, volume=0.5, sample_rate=44100):
    """Generate sine wave samples."""
    n = int(sample_rate * duration)
    return [volume * 32767 * math.sin(2 * math.pi * freq * i / sample_rate) for i in range(n)]


def fade(samples, fade_in=0.01, fade_out=0.05, sample_rate=44100):
    """Apply fade in/out envelope."""
    result = list(samples)
    fi = int(fade_in * sample_rate)
    fo = int(fade_out * sample_rate)
    for i in range(min(fi, len(result))):
        result[i] *= i / fi
    for i in range(min(fo, len(result))):
        result[-(i + 1)] *= i / fo
    return result


def mix(*sample_lists):
    """Mix multiple sample lists together."""
    max_len = max(len(s) for s in sample_lists)
    result = [0.0] * max_len
    for samples in sample_lists:
        for i, s in enumerate(samples):
            result[i] += s
    return result


def generate_champagne():
    """Bright bubbly pop — two-tone rising chord."""
    s1 = fade(sine(880, 0.25, 0.3))
    s2 = fade(sine(1320, 0.25, 0.25))
    s3 = fade(sine(1760, 0.15, 0.2))
    write_wav("champagne.wav", mix(s1, s2, s3))


def generate_whoosh():
    """Quick sweep from low to high."""
    sr = 44100
    dur = 0.3
    n = int(sr * dur)
    samples = []
    for i in range(n):
        t = i / sr
        freq = 200 + (2000 - 200) * (t / dur) ** 2
        env = math.sin(math.pi * t / dur)
        # Noise-ish via multiple detuned sines
        val = 0
        for f_mult in [1.0, 1.01, 0.99, 2.01, 0.5]:
            val += math.sin(2 * math.pi * freq * f_mult * t)
        samples.append(val / 5 * env * 0.4 * 32767)
    write_wav("whoosh.wav", samples)


def generate_chime():
    """Clean two-note ascending chime."""
    s1 = fade(sine(1047, 0.15, 0.3), fade_out=0.1)  # C6
    s2 = fade(sine(1319, 0.2, 0.3), fade_out=0.15)  # E6
    # Offset second note
    gap = [0.0] * int(44100 * 0.08)
    write_wav("chime.wav", mix(s1, gap + s2))


def generate_airhorn():
    """Big brassy blast — stacked harmonics."""
    dur = 0.8
    base = 220
    layers = []
    for harmonic in [1, 2, 3, 4, 5]:
        vol = 0.4 / harmonic
        layers.append(fade(sine(base * harmonic, dur, vol), fade_in=0.02, fade_out=0.2))
    write_wav("airhorn.wav", mix(*layers))


def generate_gong():
    """Deep resonant gong."""
    dur = 1.2
    sr = 44100
    n = int(sr * dur)
    samples = [0.0] * n
    # Inharmonic overtones typical of gong
    for freq, vol, decay in [(110, 0.4, 1.5), (163, 0.25, 2.0), (220, 0.2, 2.5),
                              (277, 0.15, 3.0), (340, 0.1, 3.5)]:
        for i in range(n):
            t = i / sr
            env = math.exp(-t * decay) * math.sin(math.pi * min(t / 0.01, 1))
            samples[i] += vol * 32767 * math.sin(2 * math.pi * freq * t) * env
    write_wav("gong.wav", samples)


def generate_ui_sounds():
    """Small UI feedback sounds."""
    # click-confirm: short blip
    write_wav("click-confirm.wav", fade(sine(1200, 0.06, 0.2), fade_out=0.03))

    # hud-open: quick ascending two-tone
    s1 = fade(sine(600, 0.05, 0.15), fade_out=0.02)
    gap = [0.0] * int(44100 * 0.02)
    s2 = fade(sine(900, 0.06, 0.15), fade_out=0.03)
    write_wav("hud-open.wav", mix(s1, gap + s2))

    # login-granted: triumphant three-note ascending
    n1 = fade(sine(523, 0.1, 0.2), fade_out=0.05)  # C5
    g1 = [0.0] * int(44100 * 0.05)
    n2 = fade(sine(659, 0.1, 0.2), fade_out=0.05)  # E5
    g2 = [0.0] * int(44100 * 0.1)
    n3 = fade(sine(784, 0.15, 0.25), fade_out=0.1)  # G5
    write_wav("login-granted.wav", mix(n1, g1 + n2, g1 + g2 + n3))


def main():
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    print("Generating Standup 3000 sound effects...")
    generate_champagne()
    generate_whoosh()
    generate_chime()
    generate_airhorn()
    generate_gong()
    generate_ui_sounds()
    print("Done! Sound files are in static/sounds/")


if __name__ == "__main__":
    main()
