"""作曲：和弦网格 + 五音动机 + 由四维曲线驱动的旋律生成。"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .core import (MAJOR, MINOR, Brief, Chord, QUAL, degree_to_midi, parse_chord)


@dataclass
class Event:
    bar: int
    beat: float
    midi: int
    dur: float
    vel: float
    role: str = "melody"


# --------------------------------------------------------------------------
# 和弦网格
# --------------------------------------------------------------------------
# 每个段落一种"功能模板"，一个模板 = 4 小节的和弦功能走向。
TEMPLATES = {
    "intro": [
        [("I", "maj9"), ("V", "13", 3), ("vi", "m9"), ("IV", "maj7")],
        [("I", "maj9"), ("iii", "m7"), ("IV", "maj7"), ("V", "sus4")],
    ],
    "A": [
        [("I", "maj9"), ("V", "13", 3), ("vi", "m9"), ("IV", "maj7")],
        [("ii", "m9"), ("V", "13"), ("I", "maj9"), ("V", "sus4")],
        [("IV", "maj7"), ("iii", "m7"), ("vi", "m9"), ("ii", "m9")],
    ],
    "B": [
        [("IV", "maj9"), ("V", "13", 4), ("iii", "m7"), ("vi", "m9")],
        [("ii", "m9"), ("V", "13"), ("I", "maj9"), ("vi", "m9")],
        [("vi", "m9"), ("IV", "maj7"), ("ii", "m9"), ("V", "sus4")],
    ],
    "climax": [
        [("ii", "m9"), ("V", "13"), ("I", "maj9"), ("vi", "m9")],
        [("IV", "maj9"), ("V", "13", 4), ("iii", "m7"), ("vi", "m9")],
        [("IVm", "m6"), ("V", "sus4"), ("I", "maj9"), ("V", "sus4")],
        [("vi", "m9"), ("ii", "m9"), ("IV", "maj7"), ("V", "13")],
    ],
    "coda": [
        [("I", "maj9"), ("IV", "maj7"), ("ii", "m9"), ("V", "sus4")],
        [("I", "maj9"), ("IV", "maj7"), ("V", "sus4"), ("I", "maj9add")],
    ],
}

_DEG = {"I": 1, "ii": 2, "iii": 3, "IV": 4, "V": 5, "vi": 6, "vii": 7, "IVm": 4}


def _root_of(brief: Brief, deg_name: str) -> int:
    d = _DEG[deg_name]
    scale = MAJOR if brief.mode == "major" else MINOR
    return (brief.key_pc + scale[d - 1]) % 12


def _chord_from(brief: Brief, deg_name: str, quality: str,
                bass_deg: int | None = None) -> Chord:
    root = _root_of(brief, deg_name)
    bass = root
    if bass_deg:
        scale = MAJOR if brief.mode == "major" else MINOR
        bass = (brief.key_pc + scale[bass_deg - 1]) % 12
    symbol = f"{deg_name}{quality}" + (f"/{bass_deg}" if bass_deg else "")
    return Chord(symbol=symbol, root_pc=root, bass_pc=bass,
                 intervals=QUAL[quality], quality=quality)


def _template_for(name: str) -> list:
    low = name.lower()
    if "intro" in low:
        return TEMPLATES["intro"]
    if "coda" in low or "outro" in low:
        return TEMPLATES["coda"]
    if "climax" in low or "peak" in low:
        return TEMPLATES["climax"]
    if low.startswith("b") or "bridge" in low:
        return TEMPLATES["B"]
    return TEMPLATES["A"]


def build_chords(brief: Brief, rng: np.random.Generator) -> list[Chord]:
    """优先用立项卡里的和弦网格；否则按段落功能模板生成。"""
    if brief.chords:
        return [parse_chord(s) for s in brief.chords]

    grid: list[Chord] = []
    for sec in brief.sections:
        tpl_pool = _template_for(sec.name)
        tpl = tpl_pool[int(rng.integers(0, len(tpl_pool)))]
        for i in range(sec.bars):
            deg, qual, *bass = tpl[i % len(tpl)]
            bass_deg = bass[0] if bass else None
            grid.append(_chord_from(brief, deg, qual, bass_deg))
    assert len(grid) == brief.bars, (len(grid), brief.bars)
    return grid


# --------------------------------------------------------------------------
# 动机
# --------------------------------------------------------------------------
DEFAULT_MOTIF = [5, 1, 3, 2, 1]          # 5–1–3–2–1：跳进后级进回落
RHYTHMS = [
    [(0.0, 1.5), (1.5, 0.5), (2.5, 1.5), (4.0, 1.0), (5.0, 1.0), (6.0, 1.5)],
    [(0.0, 2.0), (2.0, 1.0), (3.0, 1.0), (4.0, 1.5), (5.5, 0.5), (6.0, 2.0)],
    [(0.0, 1.0), (1.0, 1.0), (2.0, 1.5), (3.5, 0.5), (4.0, 2.0), (6.0, 1.5)],
]


def _register(sec) -> tuple[int, int]:
    """按距离感/唤醒度决定旋律音区（MIDI 范围）。"""
    base = 67 + int(round((sec.arousal - .35) * 10))      # G4 附近起
    span = 9 + int(round(sec.distance * 6))
    return base, base + span


def _phrase_variant(motif: list[int], rng: np.random.Generator, n: int) -> list[int]:
    kind = int(rng.integers(0, 4))
    if kind == 0:
        return list(motif)
    if kind == 1:                                  # 只改最后一个音
        out = list(motif)
        out[-1] = int(rng.choice([2, 4, 6]))
        return out
    if kind == 2:                                  # 音序倒影
        pivot = motif[0]
        return [pivot - (d - pivot) if d != pivot else d for d in motif]
    return list(reversed(motif))                   # 逆行（稀疏用法）


def build_melody(brief: Brief, chords: list[Chord],
                 rng: np.random.Generator) -> list[Event]:
    motif = brief.motif or DEFAULT_MOTIF
    events: list[Event] = []
    bar0 = 0

    for sec in brief.sections:
        lo, hi = _register(sec)
        is_intro = "intro" in sec.name.lower()
        is_coda = "coda" in sec.name.lower()

        for local in range(0, sec.bars, 2):
            bars_left = min(2, sec.bars - local)
            phrase_len = bars_left * 4
            rhythm = RHYTHMS[int(rng.integers(0, len(RHYTHMS)))]
            degs = _phrase_variant(motif, rng, len(rhythm))

            for k, (beat, dur) in enumerate(rhythm):
                if beat >= phrase_len:
                    break
                if is_intro and (local > 0 or k > 2):
                    continue
                if is_coda and local > 0 and k > 1:
                    continue
                if sec.arousal < .30 and k % 3 == 2:
                    continue                       # 低唤醒段自动稀疏

                deg = degs[k % len(degs)]
                target = degree_to_midi(brief.key_pc, brief.mode, deg, 4)
                target = min(max(target, lo), hi)

                bar = bar0 + local + int(beat // 4)
                b = beat % 4
                chord = chords[min(bar, len(chords) - 1)]
                if b in (0.0, 2.0):
                    midi = chord.next_tone(target, lo, hi)      # 强拍落和弦音
                elif k == len(rhythm) - 1:
                    midi = chord.next_tone(target + 2, lo, hi)  # 句尾悬置
                else:
                    midi = target

                # 力度：段落基线 + 乐句起伏 + 节拍重音
                vel = .40 + .32 * sec.arousal + .05 * (1 if b == 0 else 0)
                vel += .03 * math.sin((local * 4 + beat) * .9)
                vel = float(np.clip(vel, .25, .78))
                events.append(Event(bar, b, midi, dur, vel))

        bar0 += sec.bars
    return events
