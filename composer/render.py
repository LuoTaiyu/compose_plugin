"""渲染：把乐谱变成 bus，再把 bus 混成母带。"""
from __future__ import annotations

import gc
import math

import numpy as np

from . import dsp, instruments
from .compose import Event, build_chords, build_melody
from .core import Brief, Chord, Timeline, freq

SECTION_GAIN = {"intro": .92, "a": .95, "b": .96, "climax": 1.32, "a2": .90, "coda": .74}


def _gain(name: str) -> float:
    low = name.lower()
    if "intro" in low:
        return SECTION_GAIN["intro"]
    if "climax" in low or "peak" in low:
        return SECTION_GAIN["climax"]
    if "coda" in low or "outro" in low:
        return SECTION_GAIN["coda"]
    if low.startswith("b") or "bridge" in low:
        return SECTION_GAIN["b"]
    if "a2" in low or "reprise" in low:
        return SECTION_GAIN["a2"]
    return SECTION_GAIN["a"]


def _new(n: int) -> np.ndarray:
    return np.zeros((2, n), dtype=np.float32)


# --------------------------------------------------------------------------
def render_piano(brief: Brief, tl: Timeline, chords: list[Chord],
                 melody: list[Event], rng: np.random.Generator) -> np.ndarray:
    sr, n = brief.sr, tl.n
    bus = _new(n)
    cache: dict[tuple[int, int], np.ndarray] = {}

    def note(m: int, vel: float) -> np.ndarray:
        layer = 0 if vel < .28 else 1 if vel < .46 else 2
        key = (m, layer)
        if key not in cache:
            if len(cache) >= 36:
                cache.clear()
            ring = max(2.0, 4.4 - max(0, m - 45) * .045)
            cache[key] = instruments.felt_piano(freq(m), vel, ring, sr, rng)
        return cache[key]

    by_bar: dict[int, Event] = {}
    for e in melody:
        by_bar.setdefault(e.bar, e)

    for bar in range(brief.bars):
        sec, local = brief.section_of_bar(bar)
        ch = chords[bar]
        g = _gain(sec.name) * sec.gain

        # 琶音：密度与力度都跟着唤醒度分级，避免段落之间跳 4 dB
        if "intro" in sec.name.lower() and local not in (1, 3):
            pass
        else:
            a = sec.arousal
            if a < .22:
                positions, vel_base = (0.0, 2.0), .18
            elif a < .34:
                positions, vel_base = (0.0, 1.0, 2.0, 3.0), .245
            elif a < .50:
                positions, vel_base = (0.0, .5, 1.0, 1.5, 2.0, 2.5), .25
            else:
                positions, vel_base = (0.0, .5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5), .27
            idxs = (0, 2, 1, 3, 2, 4, 1, 3)
            pool = [ch.root_pc + 48] + ch.tones(3)
            for k, pos in enumerate(positions):
                m = pool[idxs[k % len(idxs)] % len(pool)]
                if "intro" in sec.name.lower():
                    m += 12
                vel = vel_base * g
                vel *= .88 + .12 * math.sin(k * 1.7 + bar * .6)
                dsp.place(bus, note(m, vel), tl.sec(bar, pos) + rng.normal(0, .008),
                          .50, .22 if k % 2 else -.22, sr)

        # 高点低八度
        if "climax" in sec.name.lower() and local % 2 == 0:
            dsp.place(bus, note(ch.root_pc + 36, .24), tl.sec(bar) + rng.normal(0, .006),
                      .34, 0.0, sr)

        # 段首滚奏和弦
        if local == 0:
            for k, m in enumerate([ch.root_pc + 48] + ch.tones(3)[:3]):
                dsp.place(bus, note(m, .26), tl.sec(bar) + k * .028 + rng.normal(0, .004),
                          .46 * g, -.2 + k * .12, sr)

    # 钢琴影子跟随旋律（A 段与尾奏）
    piano_shadow = {"A1": .30, "A2": .42, "coda": .44}
    for e in melody:
        sec, _ = brief.section_of_bar(e.bar)
        g = next((v for k, v in piano_shadow.items() if k.lower() in sec.name.lower()), 0)
        if not g:
            continue
        dur = max(.25, e.dur * tl.beat_len(e.bar))
        sig = instruments.felt_piano(freq(e.midi), e.vel * .8, min(3.9, dur + 1.2), sr, rng)
        dsp.place(bus, sig, tl.sec(e.bar, e.beat) + .010 + rng.normal(0, .006),
                  g * _gain(sec.name), -.12, sr)

    cache.clear()
    bus = dsp.eq_low_shelf(bus, 105, -1.2, .7, sr)
    bus = dsp.eq_peak(bus, 330, .8, .9, sr)
    return dsp.hp(bus, 42, 2, sr)


def render_viola(brief: Brief, tl: Timeline, melody: list[Event],
                 rng: np.random.Generator) -> np.ndarray:
    sr = brief.sr
    bus = _new(tl.n)
    prev_f, prev_end = None, -99.0
    n_ev = max(1, len(melody) - 1)
    for i, e in enumerate(melody):
        sec, _ = brief.section_of_bar(e.bar)
        if "intro" in sec.name.lower():
            continue
        phrase = i / n_ev
        gap = (e.bar * 4 + e.beat) - prev_end
        legato = prev_f is not None and 0 <= gap < .20
        dur = max(.20, e.dur * tl.beat_len(e.bar))
        sig = instruments.viola_lead(freq(e.midi), dur, e.vel, sr, rng,
                                     prev_f, legato, phrase)
        g = {"A1": .60, "B": .60, "climax": .66, "A2": .66, "coda": .58}
        gain = next((v for k, v in g.items() if k.lower() in sec.name.lower()), .58)
        at = tl.sec(e.bar, e.beat) + .015 + .007 * math.sin(phrase * 2 * math.pi + .6)
        dsp.place(bus, sig, at, gain * _gain(sec.name), -.08, sr)
        prev_f = freq(e.midi)
        prev_end = e.bar * 4 + e.beat + e.dur
    bus = dsp.hp(dsp.lp(bus, 4200, 2, sr), 120, 2, sr)
    return dsp.eq_peak(bus, 3200, -1.2, 1.0, sr)


def render_music_box(brief: Brief, tl: Timeline, melody: list[Event],
                     rng: np.random.Generator) -> np.ndarray:
    sr = brief.sr
    bus = _new(tl.n)
    cache: dict[tuple[int, int], np.ndarray] = {}
    for i, e in enumerate(melody):
        sec, local = brief.section_of_bar(e.bar)
        low = sec.name.lower()
        if "intro" in low:
            continue
        if "a1" in low and local < 8:
            continue                          # A1 后半才有回声
        if low.startswith("coda") and i % 2:
            continue
        m = e.midi + 12
        key = (m, int(e.vel * 20))
        if key not in cache:
            if len(cache) >= 40:
                cache.clear()
            cache[key] = instruments.music_box(freq(m), e.vel, sr, rng)
        dsp.place(bus, cache[key], tl.sec(e.bar, e.beat) + .032 + rng.normal(0, .008),
                  .24, .34, sr)
    return bus


def render_strings(brief: Brief, tl: Timeline, chords: list[Chord],
                   rng: np.random.Generator) -> np.ndarray:
    sr = brief.sr
    bus = _new(tl.n)
    cache: dict[tuple[int, str], np.ndarray] = {}
    for bar in range(brief.bars):
        sec, local = brief.section_of_bar(bar)
        low = sec.name.lower()
        if not ("b" in low[:1] or "climax" in low or "peak" in low):
            continue
        ch = chords[bar]
        name = "B" if low.startswith("b") else "climax"
        for k, (m, v) in enumerate(((ch.root_pc + 36, .32), (ch.root_pc + 43, .24))):
            key = (m, "c")
            if key not in cache:
                cache[key] = instruments.bowed_string(freq(m), 4.2, .45, sr, rng, "cello")
            dsp.place(bus, cache[key], tl.sec(bar) + k * .03,
                      .16 if name == "B" else .30, -.2, sr)
        for k, m in enumerate(ch.tones(4)[1:3]):
            key = (m, "v")
            if key not in cache:
                cache[key] = instruments.bowed_string(freq(m), 4.0, .36, sr, rng, "violin")
            dsp.place(bus, cache[key], tl.sec(bar) + .05 + k * .02,
                      .10 if name == "B" else .16, .25, sr)
    return dsp.lp(bus, 5400, 2, sr)


def render_harmonium(brief: Brief, tl: Timeline, chords: list[Chord]) -> np.ndarray:
    sr = brief.sr
    bus = _new(tl.n)
    cache: dict[int, np.ndarray] = {}
    for bar in range(brief.bars):
        sec, _ = brief.section_of_bar(bar)
        low = sec.name.lower()
        if not (low.startswith("b") or "climax" in low or "peak" in low):
            continue
        ch = chords[bar]
        name = "B" if low.startswith("b") else "climax"
        for k, m in enumerate(ch.tones(4)[:3]):
            if m not in cache:
                cache[m] = instruments.harmonium(freq(m), 3.9, .4, sr)
            dsp.place(bus, cache[m], tl.sec(bar), .06 if name == "B" else .12,
                      -.3 + .3 * k, sr)
    return dsp.lp(bus, 2100, 2, sr)


def render_fx(brief: Brief, tl: Timeline, chords: list[Chord],
              rng: np.random.Generator) -> np.ndarray:
    """反向钢琴 swell + 稀疏尘埃音。"""
    sr = brief.sr
    bus = _new(tl.n)
    starts, acc = [], 0
    for s in brief.sections:
        starts.append(acc)
        acc += s.bars
    for bar in starts[1:]:
        ch = chords[bar]
        for k, m in enumerate([ch.root_pc + 48] + ch.tones(3)[:3]):
            sig = instruments.felt_piano(freq(m), .45, 4.8, sr, rng)[::-1]
            dsp.place(bus, sig, tl.sec(bar) - 2.2 + k * .04, .20, -.3 + k * .2, sr)
    for bar in range(2, brief.bars - 2, 7):
        ch = chords[bar]
        m = ch.tones(5)[-1] + 12
        dsp.place(bus, instruments.music_box(freq(m), .22, sr, rng),
                  tl.sec(bar) + .1, .12, .4, sr)
    return dsp.lp(bus, 3500, 2, sr)


def add_room(master: np.ndarray, sr: int, rng: np.random.Generator,
             gain: float = .75) -> None:
    n = master.shape[1]
    chunk = int(4.0 * sr)
    for start in range(0, n, chunk):
        m = min(chunk, n - start)
        t = np.arange(start, start + m, dtype=np.float32) / sr
        gust = .55 + .45 * (.5 + .5 * np.sin(2 * math.pi * .017 * t + .8)) ** 2
        gust *= .65 + .35 * (.5 + .5 * np.sin(2 * math.pi * .006 * t + 2.1)) ** 2
        env = np.ones(m, dtype=np.float32)
        if start < sr * 4:
            env *= np.clip(t / 4.0, 0, 1)
        if start + m > n - sr * 12:
            env *= np.clip((n / sr - t) / 12.0, 0, 1)
        for ch in (0, 1):
            noise = rng.normal(0, 1, m).astype(np.float32)
            air = dsp.hp(dsp.lp(noise, 6500, 2, sr), 120, 2, sr)
            master[ch, start:start + m] += air * gust * env * .020 * gain


# --------------------------------------------------------------------------
def render_song(brief: Brief, log=print) -> tuple[np.ndarray, dict]:
    sr = brief.sr
    rng = np.random.default_rng(brief.seed)
    tl = Timeline(bars=brief.bars, meter=brief.meter, tempo_points=_tempo_points(brief),
                  sr=sr, tail=brief.tail)
    chords = build_chords(brief, rng)
    melody = build_melody(brief, chords, rng)
    log(f"  timeline  {tl.duration:.1f}s + {brief.tail:.1f}s tail = {tl.total:.1f}s")
    log(f"  chords    {len(chords)} bars, melody {len(melody)} events")

    master = _new(tl.n)
    short = np.zeros(tl.n, dtype=np.float32)
    long_ = np.zeros(tl.n, dtype=np.float32)

    def mix(bus, gain, s, l):
        nonlocal master
        bus *= gain
        master += bus
        if s or l:
            mono = bus.mean(axis=0)
            if s:
                short[:] += mono * s
            if l:
                long_[:] += mono * l
            del mono
        del bus
        gc.collect()

    log("  felt piano...")
    mix(render_piano(brief, tl, chords, melody, rng), .74, .18, .05)
    log("  muted viola...")
    mix(render_viola(brief, tl, melody, rng), .58, .26, .10)
    log("  music box...")
    mix(render_music_box(brief, tl, melody, rng), .32, .08, .38)
    log("  strings...")
    mix(render_strings(brief, tl, chords, rng), .34, .30, .0)
    log("  harmonium...")
    mix(render_harmonium(brief, tl, chords), .24, .24, .0)
    log("  reversed swells...")
    mix(render_fx(brief, tl, chords, rng), .20, .08, .18)
    log("  room tone...")
    add_room(master, sr, rng, .75)

    log("  reverb...")
    ir_s = dsp.make_ir(1.9, sr, rng, .012, 6.0, 170, 4700)
    wet_s = dsp.convolve_mono(short, ir_s) * .38
    del short, ir_s
    gc.collect()
    master += wet_s
    del wet_s
    gc.collect()

    ir_l = dsp.make_ir(4.2, sr, rng, .028, 6.0, 210, 4200)
    wet_l = dsp.convolve_mono(long_, ir_l) * .34
    del long_, ir_l
    gc.collect()
    master += wet_l
    del wet_l
    gc.collect()

    meta = dict(timeline=tl, chords=chords, melody=melody)
    return master, meta


def _tempo_points(brief: Brief) -> list[tuple[float, float]]:
    """按段落给速度锚点：开头略慢、高潮略快、结尾减速。"""
    pts, acc = [], 0
    lo, hi = brief.bpm_range
    n = len(brief.sections)
    for i, s in enumerate(brief.sections):
        low = s.name.lower()
        if "intro" in low:
            bpm = lo + (brief.bpm - lo) * .2
        elif "climax" in low or "peak" in low:
            bpm = brief.bpm + (hi - brief.bpm) * .8
        elif "coda" in low or "outro" in low:
            bpm = lo - (brief.bpm - lo) * 1.2
        else:
            bpm = brief.bpm
        pts.append((acc * 4.0, max(30.0, bpm)))
        acc += s.bars
    pts.append((brief.bars * 4.0, max(30.0, lo - (brief.bpm - lo) * 1.6)))
    return pts
