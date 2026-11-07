"""母带：EQ → 软限幅 → 淡入淡出 → 响度归一 → 真峰保护。"""
from __future__ import annotations

import math

import numpy as np

from . import dsp, qa


def limit(x: np.ndarray, sr: int, ceiling_db: float = -3.0,
          block: int = 128) -> np.ndarray:
    """前视块状限幅：块内取峰值，跨块平滑增益，再逐样本展开。

    只压瞬态，不改变段落动态——它的作用是让 −15 LUFS 与 −2.5 dBFS 真峰
    可以同时成立，而不是把整首歌压扁。
    """
    n = x.shape[1]
    ceil = 10 ** (ceiling_db / 20.0)
    mono = np.max(np.abs(x), axis=0)
    m = (n + block - 1) // block
    padded = np.pad(mono, (0, m * block - n), mode="edge").reshape(m, block)
    blk = padded.max(axis=1)

    a_att = math.exp(-block / (0.005 * sr))
    a_rel = math.exp(-block / (0.080 * sr))
    g = np.empty(m, dtype=np.float32)
    g0 = 1.0
    for i in range(m):
        need = min(1.0, ceil / max(1e-9, float(blk[i])))
        a = a_att if need < g0 else a_rel
        g0 = a * g0 + (1 - a) * need
        g[i] = g0
    gain = np.repeat(g, block)[:n]
    return (x * gain).astype(np.float32)


def master(mix: np.ndarray, sr: int, target_lufs: float = -15.0,
           target_tp: float = -2.5, fade_in: float = 2.5,
           fade_out: float = 11.0, log=print) -> tuple[np.ndarray, dict]:
    x = mix.astype(np.float32, copy=True)
    x = dsp.eq_low_shelf(x, 85, .6, .7, sr)
    x = dsp.eq_peak(x, 330, -.6, .9, sr)
    x = dsp.eq_peak(x, 2600, -.4, 1.0, sr)
    x = dsp.eq_high_shelf(x, 5600, -.8, .7, sr)
    x = dsp.hp(x, 35, 2, sr)

    peak = float(np.max(np.abs(x)))
    if peak > 0:
        x = (np.tanh(x / peak * 1.05) / math.tanh(1.05)).astype(np.float32)

    n = x.shape[1]
    fi, fo = int(fade_in * sr), int(fade_out * sr)
    if fi:
        x[:, :fi] *= np.linspace(0, 1, fi, dtype=np.float32)[None, :] ** 1.4
    if fo:
        x[:, -fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[None, :] ** 1.25

    lufs = qa.integrated_loudness(x, sr)
    # 增益与限幅互相拉扯：反复收敛，让响度与真峰同时落在目标上。
    # 限幅天花板比真峰目标再低 1.5 dB，给采样间峰值留余量。
    ceiling = target_tp - 1.5
    for _ in range(4):
        cur = qa.integrated_loudness(x, sr)
        if not math.isfinite(cur) or cur < -60:
            break
        x *= np.float32(10 ** ((target_lufs - cur) / 20.0))
        x = limit(x, sr, ceiling)
        if abs(qa.integrated_loudness(x, sr) - target_lufs) < .2:
            break
    log(f"  loudness  {lufs:.1f} → {qa.integrated_loudness(x, sr):.1f} LUFS")

    tp = qa.true_peak_dbfs(x, sr)
    if tp > target_tp:
        x *= np.float32(10 ** ((target_tp - tp) / 20.0))
        log(f"  true peak {tp:.1f} → {target_tp:.1f} dBFS")

    peak = float(np.max(np.abs(x)))
    info = dict(lufs=qa.integrated_loudness(x, sr), true_peak=qa.true_peak_dbfs(x, sr),
                peak=peak, peak_db=dsp.db(peak))
    log(f"  final     peak {peak:.3f} ({dsp.db(peak):.1f} dBFS)")
    return x, info
