"""验证：客观测量 + 阈值判定。测量不等于听感，这里只回答"是否达标"。"""
from __future__ import annotations

import math

import numpy as np

from . import dsp
from .core import Brief

BANDS = [(20, 60), (60, 120), (120, 250), (250, 500), (500, 1000),
         (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)]


# --------------------------------------------------------------------------
# 响度（BS.1770 近似：K 加权 + 400 ms 分块 + 绝对/相对门限）
# --------------------------------------------------------------------------
def _k_weight(x: np.ndarray, sr: int) -> np.ndarray:
    # 高架（头相关） + 高通（RLB）
    b1, a1 = dsp._coeffs("highshelf", 1681.97, sr, 0.7072, 3.999)
    b2, a2 = dsp._coeffs("highpass", 38.135, sr, 0.5003)
    y = dsp._apply(x, b1, a1)
    return dsp._apply(y, b2, a2)


def integrated_loudness(master: np.ndarray, sr: int) -> float:
    """返回 LUFS（立体声，双声道等权）。"""
    y = np.stack([_k_weight(master[0], sr), _k_weight(master[1], sr)])
    block = int(.4 * sr)
    hop = int(.1 * sr)
    if y.shape[1] < block:
        ms = np.mean(np.square(y))
        return -0.691 + 10 * math.log10(max(1e-12, ms))
    energies = []
    for start in range(0, y.shape[1] - block + 1, hop):
        seg = y[:, start:start + block]
        energies.append(float(np.mean(np.square(seg))))
    z = np.array(energies)
    loud = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    keep = loud > -70.0
    if not np.any(keep):
        return -70.0
    rel = -0.691 + 10 * math.log10(float(np.mean(z[keep]))) - 10.0
    keep &= loud > rel
    if not np.any(keep):
        keep = loud > -70.0
    return float(-0.691 + 10 * math.log10(float(np.mean(z[keep]))))


def true_peak_dbfs(master: np.ndarray, sr: int) -> float:
    """4× 过采样后的真峰（dBFS）。"""
    peak = 0.0
    chunk = 1 << 15
    for ch in master:
        for start in range(0, ch.shape[0], chunk):
            seg = ch[start:start + chunk]
            if seg.size < 8:
                continue
            n = seg.shape[0]
            spec = np.fft.rfft(seg)
            up = np.fft.irfft(spec, n * 4) * 4.0
            peak = max(peak, float(np.max(np.abs(up))))
    return dsp.db(peak) if peak > 0 else -120.0


# --------------------------------------------------------------------------
# 频谱
# --------------------------------------------------------------------------
def spectrum_stats(mono: np.ndarray, sr: int, nperseg: int = 8192):
    if mono.shape[0] < nperseg:
        mono = np.pad(mono, (0, nperseg - mono.shape[0]))
    hop = nperseg // 2
    window = np.hanning(nperseg).astype(np.float32)
    acc = np.zeros(nperseg // 2 + 1, dtype=np.float64)
    count = 0
    for start in range(0, mono.shape[0] - nperseg + 1, hop):
        seg = mono[start:start + nperseg] * window
        acc += np.abs(np.fft.rfft(seg)) ** 2
        count += 1
    psd = acc / max(1, count)
    freqs = np.fft.rfftfreq(nperseg, 1.0 / sr)
    total = float(np.sum(psd))
    bands = {}
    for lo, hi in BANDS:
        m = (freqs >= lo) & (freqs < hi)
        bands[(lo, hi)] = 10 * math.log10(max(1e-18, float(np.sum(psd[m])) / max(1e-18, total)))
    centroid = float(np.sum(freqs * psd) / max(1e-18, np.sum(psd)))
    return bands, centroid


def section_rms(master: np.ndarray, brief: Brief, tl) -> dict[str, float]:
    mono = master.mean(axis=0)
    out = {}
    bar = 0
    for s in brief.sections:
        t0, t1 = tl.sec(bar), tl.sec(bar + s.bars)
        seg = mono[int(t0 * brief.sr):int(t1 * brief.sr)]
        out[s.name] = dsp.rms_db(seg) if seg.size else -120.0
        bar += s.bars
    return out


def stereo_correlation(master: np.ndarray) -> float:
    a, b = master[0], master[1]
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 1.0
    return float(np.corrcoef(a, b)[0, 1])


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------
def evaluate(brief: Brief, master: np.ndarray, tl) -> dict:
    sr = brief.sr
    mono = master.mean(axis=0)
    bands, centroid = spectrum_stats(mono, sr)
    sec_rms = section_rms(master, brief, tl)
    lufs = integrated_loudness(master, sr)
    tp = true_peak_dbfs(master, sr)
    corr = stereo_correlation(master)
    dur = master.shape[1] / sr
    peak = float(np.max(np.abs(master)))

    names = [s.name for s in brief.sections]
    loud_pairs = [sec_rms[names[i + 1]] - sec_rms[names[i]] for i in range(len(names) - 1)]
    peak_idx = next((i for i, s in enumerate(brief.sections)
                     if "climax" in s.name.lower() or "peak" in s.name.lower()), None)
    if peak_idx and peak_idx > 0:
        d = sec_rms[names[peak_idx]] - sec_rms[names[peak_idx - 1]]
        pair_note = f"{names[peak_idx-1]} → {names[peak_idx]} {d:+.1f} dB"
        pair_ok = d <= 1.5
    else:
        middle = loud_pairs[1:] or loud_pairs      # 跳过 intro：开头本来就轻
        pair_ok = all(abs(d) <= 2.0 for d in middle)
        pair_note = " / ".join(f"{d:+.1f}" for d in middle)

    checks = []

    def chk(label, ok, detail):
        checks.append(dict(label=label, ok=bool(ok), detail=detail))

    chk("综合响度 -16 ~ -14 LUFS", -16.0 <= lufs <= -14.0, f"{lufs:.1f} LUFS")
    chk("真峰 <= -1.0 dBFS", tp <= -1.0, f"{tp:.1f} dBFS")
    chk("采样峰值 <= 0.85", peak <= .85, f"{peak:.3f} ({dsp.db(peak):.1f} dBFS)")
    chk("立体声相关 0.85-0.95", .85 <= corr <= .95, f"{corr:.3f}")
    chk("频谱重心 300-800 Hz", 300 <= centroid <= 800, f"{centroid:.0f} Hz")
    chk("高点段 RMS 只比前段高 <= 1.5 dB", pair_ok, pair_note)
    rises = [d for d in loud_pairs[1:]] if len(loud_pairs) > 2 else list(loud_pairs)
    chk("中段上行跳变 <= 2.0 dB（撤退不算）", all(d <= 2.0 for d in rises),
        " / ".join(f"{d:+.1f}" for d in loud_pairs))
    chk("时长与时间轴一致", abs(dur - tl.total) < .5, f"{dur:.1f}s vs {tl.total:.1f}s")
    chk("无 NaN / Inf", bool(np.isfinite(master).all()), "finite")

    return dict(lufs=lufs, true_peak=tp, peak=peak, corr=corr, centroid=centroid,
                bands=bands, section_rms=sec_rms, checks=checks,
                duration=dur, passed=all(c["ok"] for c in checks))


def format_report(res: dict, brief: Brief) -> str:
    lines = [f"# QA 报告：{brief.title} / {brief.title_en}", ""]
    lines.append(f"- 时长 {res['duration']:.1f}s（{int(res['duration']//60)}:{res['duration']%60:04.1f}）")
    lines.append(f"- 综合响度 {res['lufs']:.1f} LUFS（BS.1770 近似）")
    lines.append(f"- 真峰 {res['true_peak']:.1f} dBFS；采样峰值 {res['peak']:.3f}")
    lines.append(f"- 立体声相关 {res['corr']:.3f}；频谱重心 {res['centroid']:.0f} Hz")
    lines += ["", "## 分段 RMS", ""]
    for name, v in res["section_rms"].items():
        lines.append(f"- {name}: {v:.1f} dBFS")
    lines += ["", "## 频段能量（相对全频）", ""]
    for (lo, hi), v in res["bands"].items():
        lines.append(f"- {lo:>5}–{hi:<5} Hz: {v:.1f} dB")
    lines += ["", "## 阈值判定", ""]
    for c in res["checks"]:
        lines.append(f"- {'PASS' if c['ok'] else 'FAIL'} · {c['label']} — {c['detail']}")
    lines += ["", f"**总体：{'通过' if res['passed'] else '未通过'}**", ""]
    lines.append("> 以上为信号测量，不是听感评价；未做盲听，不得声称听感已验证。")
    return "\n".join(lines)
