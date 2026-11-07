"""乐器：按《音乐制作固定流程》第 6 节的参数卡逐件实现。

每件乐器都遵守同一条约束：力度同时改变音量、起音、噪声与泛音，
并且起音 / 持续 / 释放各有结构。
"""
from __future__ import annotations

import math

import numpy as np

from . import dsp


def _env(n: int, sr: int, attack: float, release: float,
         curve: float = 1.0, ring: float | None = None) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / sr
    a = np.clip(t / max(1e-4, attack), 0, 1)
    r = np.clip(((ring if ring is not None else n / sr) - t) / max(1e-4, release), 0, 1) ** curve
    return (a * r).astype(np.float32)


# --------------------------------------------------------------------------
def felt_piano(f: float, vel: float, ring: float, sr: int,
               rng: np.random.Generator) -> np.ndarray:
    n = max(1, int((ring + .5) * sr))
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    B = .00045
    for h in range(1, 11):
        fh = f * h * math.sqrt(1 + B * h * h)
        tau = (2.8 / (1 + .26 * h)) * (.65 + .55 * vel)
        amp = (1 / h ** 1.65) * (.48 + .52 * vel)
        if h > 5:
            amp *= .55
        decay = np.exp(-t / tau)
        out += .62 * amp * np.sin(2 * math.pi * fh * .9997 * t + h * .31) * decay
        out += .38 * amp * np.sin(2 * math.pi * fh * 1.0003 * t + h * 1.17) * decay
    hammer = dsp.bp(rng.normal(0, 1, n).astype(np.float32), 550, 3800, 2, sr)
    hammer *= np.exp(-t * 62) * (.006 + .016 * vel)
    thump = np.sin(2 * math.pi * 70 * t) * np.exp(-t * 24) * .018 * vel
    out = dsp.eq_peak(out, 180, 2.4, .8, sr)
    out = dsp.eq_peak(out, 560, 1.4, .95, sr)
    out = dsp.lp(out, 6000, 2, sr) + hammer + thump
    out *= _env(n, sr, .014, .28, 1.15, ring)
    return dsp.clickless(out * .46, 2.5, sr)


def music_box(f: float, vel: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    ring = 3.4
    n = max(1, int((ring + .3) * sr))
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    for ratio, amp, tau, det in ((1.0, 1.0, 2.4, .0004), (2.76, .26, .9, .0007),
                                 (5.40, .09, .45, .0012), (8.93, .025, .28, .0016)):
        fh = f * ratio * (1 + det)
        out += amp * np.sin(2 * math.pi * fh * t + ratio) * np.exp(-t / tau)
    mallet = dsp.bp(rng.normal(0, 1, n).astype(np.float32), 3500, 10500, 2, sr)
    mallet *= np.exp(-t * 95) * (.010 + .022 * vel)
    out = dsp.lp(out + mallet, 6800, 2, sr)
    out *= _env(n, sr, .002, .2, 1.0, ring)
    return dsp.clickless(out * .30, 1.5, sr)


def viola_lead(f: float, dur: float, vel: float, sr: int,
               rng: np.random.Generator, prev_f: float | None = None,
               legato: bool = False, phrase_pos: float = .5) -> np.ndarray:
    rel = .38
    n = max(1, int((dur + rel) * sr))
    t = np.arange(n, dtype=np.float32) / sr
    cents = 1.0 * math.sin(phrase_pos * 5.7 + .3) + .6 * math.sin(phrase_pos * 14.3 + 1.1)
    if legato and prev_f:
        f0 = prev_f + (f - prev_f) * (1 - np.exp(-t / .085))
    else:
        f0 = f * 2 ** ((-1.4 * np.exp(-t / .11)) / 1200)
    f0 = f0 * 2 ** (cents / 1200)
    vib = 1 + (.0011 + .0012 * vel) * np.sin(2 * math.pi * 4.3 * t + .5) \
        * np.clip((t - .20) / .45, 0, 1)
    phase = 2 * math.pi * np.cumsum(f0 * vib) / sr
    out = np.zeros(n, dtype=np.float32)
    for h in range(1, 9):
        amp = (1 / h ** 1.55) * math.exp(-h * .10)
        tau = 3.2 / (1 + .22 * h)
        out += amp * np.sin(h * phase + h * .42) * np.exp(-t / tau)
    out = dsp.eq_peak(out, 280, 2.0, .7, sr)
    out = dsp.eq_peak(out, 680, 1.4, .8, sr)
    out = dsp.eq_peak(out, 1500, .6, 1.0, sr)
    out = dsp.eq_peak(out, 3300, -1.6, 1.1, sr)
    bow = dsp.bp(rng.normal(0, 1, n).astype(np.float32), 280, 2600, 2, sr)
    bow *= (.010 + .020 * vel) * np.minimum(1, t / .12) * (.7 + .3 * np.sin(2 * math.pi * .55 * t + 1.0))
    env = _env(n, sr, .075 + .025 * (1 - vel), rel, 1.15, dur + rel)
    sig = (out * .42 + bow) * env
    sig = dsp.lp(sig, 3800 + 600 * vel, 4, sr)
    sig = dsp.hp(sig, 110, 2, sr)
    return dsp.clickless(sig * .44, 4.0, sr)


def bowed_string(f: float, dur: float, vel: float, sr: int,
                 rng: np.random.Generator, kind: str = "cello") -> np.ndarray:
    n = max(1, int((dur + .7) * sr))
    t = np.arange(n, dtype=np.float32) / sr
    vib = 1 + .0016 * np.sin(2 * math.pi * (4.3 + .3 * vel) * t + .4) * np.clip((t - .25) / .4, 0, 1)
    phase = 2 * math.pi * np.cumsum(f * vib) / sr
    out = np.zeros(n, dtype=np.float32)
    for h in range(1, 9):
        out += (1 / h ** 1.28) * np.sin(h * phase + h * .3)
    bow = dsp.bp(rng.normal(0, 1, n).astype(np.float32), 400, 3600, 2, sr)
    out += bow * (.010 + .018 * vel) * np.minimum(1, t / .3)
    if kind == "cello":
        out = dsp.eq_peak(out, 240, 2.2, .7, sr)
        out = dsp.eq_peak(out, 520, 1.4, .8, sr)
        cut = 3400
    else:
        out = dsp.eq_peak(out, 380, 1.6, .8, sr)
        out = dsp.eq_peak(out, 950, 1.3, .9, sr)
        cut = 5200
    out = dsp.lp(out, cut, 2, sr)
    out *= _env(n, sr, .35, .55, 1.0, dur + .55)
    return dsp.clickless(out * .26, 4.0, sr)


def harmonium(f: float, dur: float, vel: float, sr: int) -> np.ndarray:
    n = max(1, int((dur + .5) * sr))
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    for h in range(1, 11):
        amp = (1 / h ** 1.5) * (1.0 if h % 2 else .55)
        out += amp * np.sin(2 * math.pi * f * h * t + h * .4)
    out = dsp.lp(out, 1900, 2, sr)
    env = _env(n, sr, .4, .4, 1.0, dur + .4)
    breath = 1 + .05 * np.sin(2 * math.pi * .23 * t + .7)
    out *= env * breath
    return dsp.clickless(out * .11 * (.6 + .6 * vel), 4.0, sr)
