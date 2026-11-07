"""DSP 基元：滤波、EQ、卷积、声像与摆放。

有 scipy 时走 scipy.signal.lfilter（快）；没有 scipy 时把二阶节转成
脉冲响应再做 overlap-add 卷积，结果等价，只是慢一些。
"""
from __future__ import annotations

import math

import numpy as np

try:  # 可选依赖
    from scipy.signal import lfilter as _lfilter
    HAVE_SCIPY = True
except Exception:  # pragma: no cover
    _lfilter = None
    HAVE_SCIPY = False


# --------------------------------------------------------------------------
# 基础
# --------------------------------------------------------------------------
def db(x: float) -> float:
    return 20.0 * math.log10(max(1e-12, float(x)))


def rms_db(x: np.ndarray) -> float:
    return db(float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))))


def clickless(x: np.ndarray, ms: float = 3.0, sr: int = 48000) -> np.ndarray:
    n = min(x.shape[-1], int(sr * ms / 1000))
    if n <= 1:
        return x
    x = x.copy()
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    x[..., :n] *= ramp
    x[..., -n:] *= ramp[::-1]
    return x


def pan2(x: np.ndarray, pan: float) -> np.ndarray:
    th = (max(-1.0, min(1.0, pan)) + 1.0) * math.pi / 4
    return np.stack([x * math.cos(th), x * math.sin(th)]).astype(np.float32)


def place(bus: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0,
          pan: float = 0.0, sr: int = 48000) -> None:
    """把单声道或立体声片段叠加进 bus（就地）。"""
    if sig.ndim == 1:
        sig = pan2(sig, pan)
    i = int(round(at * sr))
    if i >= bus.shape[1]:
        return
    if i < 0:
        sig = sig[:, -i:]
        i = 0
    m = min(sig.shape[1], bus.shape[1] - i)
    if m > 0:
        bus[:, i:i + m] += sig[:, :m] * gain


# --------------------------------------------------------------------------
# RBJ biquad 系数
# --------------------------------------------------------------------------
def _coeffs(kind: str, f0: float, fs: int, q: float = 0.707, gain_db: float = 0.0):
    f0 = min(max(f0, 10.0), fs * 0.49)
    w0 = 2 * math.pi * f0 / fs
    c, s = math.cos(w0), math.sin(w0)
    alpha = s / (2 * q)
    A = 10 ** (gain_db / 40.0)
    if kind == "lowpass":
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
        a = [1 + alpha, -2 * c, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
        a = [1 + alpha, -2 * c, 1 - alpha]
    elif kind == "peaking":
        b = [1 + alpha * A, -2 * c, 1 - alpha * A]
        a = [1 + alpha / A, -2 * c, 1 - alpha / A]
    elif kind == "lowshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c),
             A * ((A + 1) - (A - 1) * c - sq)]
        a = [(A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c),
             (A + 1) + (A - 1) * c - sq]
    elif kind == "highshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c),
             A * ((A + 1) + (A - 1) * c - sq)]
        a = [(A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c),
             (A + 1) - (A - 1) * c - sq]
    else:
        raise ValueError(kind)
    a0 = a[0]
    return (np.array(b, dtype=np.float64) / a0, np.array(a, dtype=np.float64) / a0)


def _impulse(b: np.ndarray, a: np.ndarray, n: int = 2048) -> np.ndarray:
    h = np.zeros(n, dtype=np.float32)
    h[0] = 1.0
    x1 = x2 = y1 = y2 = 0.0
    b0, b1, b2 = b
    a1, a2 = a[1], a[2]
    for i in range(n):
        x0 = 1.0 if i == 0 else 0.0
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        h[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return h


def _ola(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    n, L = x.shape[-1], h.shape[0]
    if L <= 1:
        return x * h[0]
    step = 1 << 15
    nfft = 1 << int(math.ceil(math.log2(step + L - 1)))
    H = np.fft.rfft(h.astype(np.float64), nfft)
    y = np.zeros(n + L - 1, dtype=np.float32)
    for i in range(0, n, step):
        seg = x[i:i + step]
        if seg.size == 0:
            break
        Y = np.fft.irfft(np.fft.rfft(seg, nfft) * H, nfft)[: y.shape[0] - i]
        y[i:i + Y.size] += Y.astype(np.float32)
    return y[:n]


def _apply(x: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    if HAVE_SCIPY:
        return _lfilter(b, a, x, axis=-1).astype(np.float32)
    h = _impulse(b, a)
    if x.ndim == 1:
        return _ola(x, h)
    return np.stack([_ola(ch, h) for ch in x])


# --------------------------------------------------------------------------
# 常用滤波（二阶；order>2 时级联）
# --------------------------------------------------------------------------
def lp(x, f, order=2, sr=48000):
    for _ in range(max(1, order // 2)):
        x = _apply(x, *_coeffs("lowpass", f, sr, 0.707))
    return x


def hp(x, f, order=2, sr=48000):
    for _ in range(max(1, order // 2)):
        x = _apply(x, *_coeffs("highpass", f, sr, 0.707))
    return x


def bp(x, lo, hi, order=2, sr=48000):
    return lp(hp(x, lo, order, sr), hi, order, sr)


def eq_peak(x, f0, gain_db, q=0.9, sr=48000):
    return _apply(x, *_coeffs("peaking", f0, sr, q, gain_db))


def eq_low_shelf(x, f0, gain_db, q=0.7, sr=48000):
    return _apply(x, *_coeffs("lowshelf", f0, sr, q, gain_db))


def eq_high_shelf(x, f0, gain_db, q=0.7, sr=48000):
    return _apply(x, *_coeffs("highshelf", f0, sr, q, gain_db))


# --------------------------------------------------------------------------
# 卷积混响
# --------------------------------------------------------------------------
def make_ir(seconds: float, sr: int, rng: np.random.Generator,
            predelay: float = 0.012, decay: float = 6.0,
            lo: float = 170.0, hi: float = 5600.0) -> np.ndarray:
    n = max(2, int(seconds * sr))
    t = np.arange(n, dtype=np.float32) / sr
    chans = []
    for _ in range(2):
        noise = rng.normal(0, 1, n).astype(np.float32)
        ir = noise * np.exp(-t * (decay / seconds))
        for d, g in ((0.011, .5), (0.019, .3), (0.031, .2), (0.047, .12), (0.073, .08)):
            i = int(d * sr)
            if i < n:
                ir[i] += g * noise[i]
        ir = hp(lp(ir, hi, 2, sr), lo, 2, sr)
        pd = int(predelay * sr)
        ir = np.pad(ir, (pd, 0))[:n]
        ir[:pd] *= np.linspace(0, 1, pd, dtype=np.float32)
        ir /= max(1e-9, float(np.sqrt(np.sum(ir ** 2))))
        chans.append(ir.astype(np.float32))
    return np.stack(chans)


def convolve_mono(send: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """单声道发送 × 立体声 IR → 立体声湿声。"""
    return np.stack([_ola(send, ir[0]), _ola(send, ir[1])]).astype(np.float32)
