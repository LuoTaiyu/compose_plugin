"""乐理、时间轴与立项卡：整个工具的地基。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# 音高
# --------------------------------------------------------------------------
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def pc_of(name: str) -> int:
    letter = name[0].upper()
    i, acc = 1, 0
    while i < len(name) and name[i] in "#b":
        acc += 1 if name[i] == "#" else -1
        i += 1
    return (_PC[letter] + acc) % 12


def midi_of(name: str) -> int:
    letter = name[0].upper()
    i, acc = 1, 0
    while i < len(name) and name[i] in "#b":
        acc += 1 if name[i] == "#" else -1
        i += 1
    return 12 * (int(name[i:]) + 1) + _PC[letter] + acc


def freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def note_name(midi: int, flats: bool = True) -> str:
    table = _NAMES_FLAT if flats else _NAMES_SHARP
    return f"{table[midi % 12]}{midi // 12 - 1}"


def pretty_key(key: str) -> str:
    """Db → D♭，C# → C♯（用于封面与文档显示）。"""
    return key.replace("b", "♭").replace("#", "♯")


_QUAL_DISPLAY = {"maj": "maj", "maj7": "maj7", "maj9": "maj9", "m9": "m9",
                 "m7": "m7", "m6": "m6", "13": "13", "9": "9",
                 "sus4": "sus4", "maj9add": "maj9(add9)"}


def chord_symbol(ch: "Chord", flats: bool = True) -> str:
    """把内部和弦对象还原成可读符号，如 Dbmaj9、Ab13/C（ASCII 升降号，便于出图）。"""
    root = note_name(ch.root_pc + 60, flats)[:-1]
    s = root + _QUAL_DISPLAY.get(ch.quality, ch.quality)
    if ch.bass_pc != ch.root_pc:
        s += "/" + note_name(ch.bass_pc + 60, flats)[:-1]
    return s


# --------------------------------------------------------------------------
# 和弦
# --------------------------------------------------------------------------
QUAL = {
    "maj9": [0, 4, 7, 11, 14],
    "maj7": [0, 4, 7, 11],
    "maj": [0, 4, 7],
    "m9": [0, 3, 7, 10, 14],
    "m7": [0, 3, 7, 10],
    "m6": [0, 3, 7, 9],
    "13": [0, 4, 7, 10, 14, 21],
    "9": [0, 4, 7, 10, 14],
    "sus4": [0, 5, 7, 10],
    "6": [0, 4, 7, 9],
    "maj9add": [0, 4, 7, 11, 14, 16],
}

_CHORD_RE = re.compile(r"^([A-G][#b]?)(.*)$")


@dataclass
class Chord:
    symbol: str
    root_pc: int
    bass_pc: int
    intervals: list[int]
    quality: str

    @property
    def pcs(self) -> list[int]:
        return sorted({(self.root_pc + i) % 12 for i in self.intervals})

    def tones(self, octave: int = 3) -> list[int]:
        """从 root 的高八度开始、升序排列的和弦音（用于铺底）。"""
        base = self.root_pc + 12 * (octave + 1)
        return sorted(base + i for i in self.intervals)

    def next_tone(self, target: int, lo: int, hi: int) -> int:
        """取离 target 最近、落在 [lo,hi] 内的和弦音。"""
        cands = [m for m in range(lo, hi + 1) if m % 12 in self.pcs]
        if not cands:
            return max(lo, min(hi, target))
        return min(cands, key=lambda m: (abs(m - target), m))


def parse_chord(symbol: str) -> Chord:
    s = symbol.strip().replace("(", "").replace(")", "")
    bass_pc = None
    if "/" in s:
        body, bass = s.split("/", 1)
        s = body
        bass_pc = pc_of(bass.strip())
    m = _CHORD_RE.match(s)
    if not m:
        raise ValueError(f"无法解析和弦：{symbol}")
    root, qual = m.group(1), m.group(2) or "maj"
    qual = qual.replace("add9", "maj9add") if qual == "maj9(add9)" else qual
    if qual not in QUAL:
        raise ValueError(f"未知和弦性质：{symbol}（{qual}）")
    root_pc = pc_of(root)
    return Chord(symbol=symbol, root_pc=root_pc,
                 bass_pc=root_pc if bass_pc is None else bass_pc,
                 intervals=QUAL[qual], quality=qual)


# --------------------------------------------------------------------------
# 音阶
# --------------------------------------------------------------------------
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]          # 自然小调


def degree_to_midi(key_pc: int, mode: str, degree: int, octave: int = 4) -> int:
    """音级 1..7（可越界，用 >=8 表示高八度继续）→ MIDI。"""
    scale = MAJOR if mode == "major" else MINOR
    d = degree - 1
    oct_shift, idx = divmod(d, 7)
    return key_pc + 12 * (octave + 1) + scale[idx] + 12 * oct_shift


# --------------------------------------------------------------------------
# 时间轴
# --------------------------------------------------------------------------
@dataclass
class Timeline:
    bars: int
    meter: int
    tempo_points: list[tuple[float, float]]   # (拍, BPM)
    sr: int
    tail: float = 7.0

    def __post_init__(self):
        self.total_beats = self.bars * self.meter
        grid = np.arange(0, self.total_beats + 1e-3, 0.01)
        bpm = np.interp(grid, [p[0] for p in self.tempo_points],
                        [p[1] for p in self.tempo_points])
        t = np.concatenate([[0.0], np.cumsum(60.0 / bpm[:-1] * 0.01)])
        self._grid, self._time = grid, t
        self.duration = float(t[-1])
        self.total = self.duration + self.tail
        self.n = int(round(self.total * self.sr))

    def beat_to_sec(self, beat: float) -> float:
        return float(np.interp(beat, self._grid, self._time))

    def sec(self, bar: float, beat: float = 0.0) -> float:
        return self.beat_to_sec(bar * self.meter + beat)

    def beat_len(self, bar: float) -> float:
        return (self.sec(bar + 1) - self.sec(bar)) / self.meter


# --------------------------------------------------------------------------
# 立项卡
# --------------------------------------------------------------------------
BRIEF_FIELDS = [
    "title", "title_en", "artist", "style", "key", "mode", "bpm", "bpm_range",
    "meter", "bars", "sections", "palette", "avoid", "seed", "logline",
]


@dataclass
class Section:
    name: str
    bars: int
    valence: float = 0.4
    arousal: float = 0.35
    tension: float = 0.35
    distance: float = 0.45
    mood: str = ""
    instruments: list[str] = field(default_factory=list)
    gain: float = 1.0


@dataclass
class Brief:
    title: str
    title_en: str
    artist: str
    style: str
    key: str
    mode: str
    bpm: float
    bpm_range: tuple[float, float]
    meter: int
    bars: int
    sections: list[Section]
    palette: list[str]
    avoid: list[str]
    seed: int
    logline: str
    chords: list[str] | None = None
    motif: list[int] | None = None
    tail: float = 7.0
    sr: int = 48000
    source: Path | None = None

    # -- 派生 --
    @property
    def key_pc(self) -> int:
        return pc_of(self.key)

    def section_of_bar(self, bar: int):
        start = 0
        for s in self.sections:
            if start <= bar < start + s.bars:
                return s, bar - start
            start += s.bars
        return self.sections[-1], max(0, self.bars - 1 - start)

    def coda_last_bar(self) -> int:
        return sum(s.bars for s in self.sections) - 1

    def validate(self) -> list[str]:
        errs = []
        total = sum(s.bars for s in self.sections)
        if total != self.bars:
            errs.append(f"段落小节数之和 {total} != bars {self.bars}")
        if self.chords is not None and len(self.chords) != self.bars:
            errs.append(f"和弦网格 {len(self.chords)} 项 != bars {self.bars}")
        if not (20 <= self.bpm <= 200):
            errs.append(f"bpm 超出合理范围：{self.bpm}")
        if self.mode not in ("major", "minor"):
            errs.append(f"mode 必须是 major 或 minor：{self.mode}")
        if len(self.avoid) < 4:
            errs.append(f"避免项至少 4 条，当前 {len(self.avoid)} 条")
        if len(self.palette) > 6:
            errs.append(f"核心音色最多 6 件，当前 {len(self.palette)} 件")
        return errs


def load_brief(path: str | Path) -> Brief:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in BRIEF_FIELDS if k not in raw]
    if missing:
        raise ValueError(f"立项卡缺少字段：{missing}")

    sections = []
    for s in raw["sections"]:
        sections.append(Section(
            name=s["name"], bars=int(s["bars"]),
            valence=float(s.get("valence", .4)),
            arousal=float(s.get("arousal", .35)),
            tension=float(s.get("tension", .35)),
            distance=float(s.get("distance", .45)),
            mood=s.get("mood", ""),
            instruments=s.get("instruments", []),
            gain=float(s.get("gain", 1.0)),
        ))

    lo, hi = raw["bpm_range"]
    brief = Brief(
        title=raw["title"], title_en=raw["title_en"], artist=raw["artist"],
        style=raw["style"], key=raw["key"], mode=raw["mode"],
        bpm=float(raw["bpm"]), bpm_range=(float(lo), float(hi)),
        meter=int(raw["meter"]), bars=int(raw["bars"]), sections=sections,
        palette=raw["palette"], avoid=raw["avoid"], seed=int(raw["seed"]),
        logline=raw["logline"], chords=raw.get("chords"),
        motif=raw.get("motif"), tail=float(raw.get("tail", 7.0)),
        sr=int(raw.get("sample_rate", 48000)), source=p,
    )
    errs = brief.validate()
    if errs:
        raise ValueError("立项卡校验失败：\n  - " + "\n  - ".join(errs))
    return brief
