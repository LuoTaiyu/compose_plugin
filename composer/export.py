"""交付：WAV 24-bit、MIDI、封面、创作手记 PDF、README。"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .core import Brief, Chord, chord_symbol, note_name, pretty_key

# --------------------------------------------------------------------------
# WAV
# --------------------------------------------------------------------------
def write_wav24(path: Path, x: np.ndarray, sr: int) -> None:
    inter = np.stack([x[0], x[1]], axis=1)
    i32 = np.clip(np.round(inter * 8388607.0), -8388608, 8388607).astype(np.int32)
    raw = i32.view(np.uint8).reshape(-1, 4)[:, :3]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(sr)
        w.writeframes(raw.tobytes())


# --------------------------------------------------------------------------
# MIDI（自写 SMF，不依赖第三方库）
# --------------------------------------------------------------------------
def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


class _Track:
    def __init__(self, name: str = ""):
        self.events: list[tuple[int, int, bytes]] = []
        if name:
            data = name.encode("utf-8")
            self.events.append((0, 0, b"\xff\x03" + _vlq(len(data)) + data))

    def add(self, tick: int, order: int, payload: bytes) -> None:
        self.events.append((max(0, int(tick)), order, payload))

    def note(self, tick: int, dur: int, pitch: int, vel: int, ch: int) -> None:
        pitch = int(np.clip(pitch, 0, 127))
        vel = int(np.clip(vel, 1, 127))
        self.add(tick, 2, bytes([0x90 | ch, pitch, vel]))
        self.add(tick + max(1, dur), 1, bytes([0x80 | ch, pitch, 0]))

    def bytes(self) -> bytes:
        self.events.sort(key=lambda e: (e[0], e[1]))
        body, last = bytearray(), 0
        for tick, _, payload in self.events:
            body += _vlq(tick - last) + payload
            last = tick
        body += _vlq(0) + b"\xff\x2f\x00"
        return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


KEY_SF = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
          "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}


def write_midi(path: Path, brief: Brief, chords: list[Chord], melody, tl) -> None:
    tpq = 480
    tick = lambda bar, beat=0.0: int(round((bar * 4 + beat) * tpq))  # noqa: E731

    meta = _Track("Composer Sketch")
    tempo = int(round(60_000_000 / brief.bpm))
    meta.add(0, 0, b"\xff\x51\x03" + tempo.to_bytes(3, "big"))
    meta.add(0, 0, b"\xff\x58\x04" + bytes([brief.meter, 2, 24, 8]))
    sf = KEY_SF.get(brief.key, 0) + (3 if brief.mode == "minor" else 0)
    mi = 1 if brief.mode == "minor" else 0
    meta.add(0, 0, b"\xff\x59\x02" + struct.pack(">bB", max(-7, min(7, sf)), mi))

    bar0 = 0
    for s in brief.sections:
        txt = f"{s.name} @ bar {bar0}".encode("utf-8")
        meta.add(tick(bar0), 0, b"\xff\x06" + _vlq(len(txt)) + txt)
        bar0 += s.bars
    meta.add(tick(brief.bars), 0, b"\xff\x06" + _vlq(6) + b"end")
    meta.add(tick(brief.bars), 0, b"\xff\x2f\x00")

    mel = _Track("Viola (melody)")
    mel.add(0, 0, bytes([0xC0, 41]))
    for e in melody:
        mel.note(tick(e.bar, e.beat), int(e.dur * tpq * .95), e.midi,
                 int(e.vel * 100), 0)

    pno = _Track("Piano chords")
    pno.add(0, 0, bytes([0xC1, 0]))
    for bar, ch in enumerate(chords):
        for k, m in enumerate([ch.root_pc + 48] + ch.tones(3)[:3]):
            pno.note(tick(bar) + k * 25, 4 * tpq - 20 - k * 25, m, 45, 1)

    box = _Track("Music box")
    box.add(0, 0, bytes([0xC2, 10]))
    for e in melody:
        if "intro" in brief.section_of_bar(e.bar)[0].name.lower():
            continue
        box.note(tick(e.bar, e.beat), int(e.dur * tpq * .9), e.midi + 12,
                 int(max(.2, e.vel) * 70), 2)

    strings = _Track("Strings")
    strings.add(0, 0, bytes([0xC3, 48]))
    for bar, ch in enumerate(chords):
        low = brief.section_of_bar(bar)[0].name.lower()
        if not (low.startswith("b") or "climax" in low):
            continue
        for m in (ch.root_pc + 36, ch.root_pc + 43):
            strings.note(tick(bar), 4 * tpq - 30, m, 55, 3)

    tracks = [meta, mel, pno, box, strings]
    body = b"".join(t.bytes() for t in tracks)
    head = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), tpq)
    path.write_bytes(head + body)


# --------------------------------------------------------------------------
# 封面
# --------------------------------------------------------------------------
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
        except Exception:
            return ImageFont.load_default()


def make_cover(path: Path, brief: Brief, size: int = 3000) -> None:
    rng = np.random.default_rng(7)
    W = H = size
    y = np.linspace(0, 1, H)[:, None]
    base = np.zeros((H, W, 3), dtype=np.float32)
    base[..., 0] = 18 + 42 * (1 - y)
    base[..., 1] = 12 + 30 * (1 - y)
    base[..., 2] = 9 + 20 * (1 - y)

    yy, xx = np.mgrid[0:H, 0:W]
    for cx, cy, r, color, amp in ((2100, 850, 1250, (230, 185, 125), .55),
                                  (1500, 1500, 1600, (150, 105, 65), .30),
                                  (650, 2300, 1100, (80, 55, 38), .20)):
        cx, cy, r = cx * size // 3000, cy * size // 3000, r * size // 3000
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        g = np.clip(1 - d, 0, 1) ** 2 * amp
        for k in range(3):
            base[..., k] += color[k] * g

    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    s = size / 3000

    win = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(win).polygon(
        [(1350 * s, 260 * s), (2470 * s, 120 * s),
         (2620 * s, 1850 * s), (1500 * s, 1980 * s)],
        fill=(255, 223, 170, 48))
    img = Image.alpha_composite(img, win.filter(ImageFilter.GaussianBlur(90 * s)))

    keys = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kd = ImageDraw.Draw(keys)
    top = 2440 * s
    for i in range(34):
        x0 = (120 + i * 84) * s
        kd.line([(x0, top), (x0 - 90 * s, H)], fill=(225, 205, 175, 26), width=max(1, int(2 * s)))
    for j in range(5):
        yl = top + j * 32 * s
        kd.line([(0, yl), (W, yl - 60 * s)], fill=(225, 205, 175, 10), width=max(1, int(2 * s)))
    img = Image.alpha_composite(img, keys.filter(ImageFilter.GaussianBlur(1.2)))

    dust = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dust)
    for _ in range(180):
        dx = rng.normal(1900, 650) * s
        dy = rng.normal(1100, 700) * s
        r = rng.uniform(.6, 3.4) * s
        dd.ellipse([dx - r, dy - r, dx + r, dy + r],
                   fill=(255, 238, 205, int(rng.uniform(20, 90))))
    img = Image.alpha_composite(img, dust.filter(ImageFilter.GaussianBlur(1.1)))

    arr = np.array(img.convert("RGB")).astype(np.float32)
    gx = np.linspace(-1, 1, W)[None, :]
    gy = np.linspace(-1, 1, H)[:, None]
    vig = np.clip(1 - .55 * np.sqrt((gx * .85) ** 2 + (gy * .9) ** 2), 0, 1)[..., None]
    img = Image.fromarray(np.clip(arr * vig, 0, 255).astype(np.uint8), "RGB")

    d = ImageDraw.Draw(img)
    f_artist = _font("C:/Windows/Fonts/bahnschrift.ttf", int(34 * s))
    f_tech = _font("C:/Windows/Fonts/bahnschrift.ttf", int(24 * s))
    f_title = _font("C:/Windows/Fonts/STZHONGS.TTF", int(300 * s))
    f_en = _font("C:/Windows/Fonts/georgia.ttf", int(70 * s))
    f_small = _font("C:/Windows/Fonts/Dengl.ttf", int(28 * s))

    d.text((190 * s, 150 * s), brief.artist, font=f_artist, fill=(235, 205, 160, 235))
    d.text((W - 190 * s, 150 * s), "NT-003 / 2026", font=f_tech, fill=(220, 200, 175, 150), anchor="ra")

    x0 = 190 * s
    for ch in brief.title:
        d.text((x0, 1090 * s), ch, font=f_title, fill=(247, 236, 218, 255))
        x0 += 330 * s

    txt, x = brief.title_en, 200 * s
    for ch in txt:
        d.text((x, 1490 * s), ch, font=f_en, fill=(240, 221, 195, 235))
        x += d.textlength(ch, font=f_en) + 12 * s

    d.line([(200 * s, 1620 * s), (760 * s, 1620 * s)], fill=(220, 180, 120, 180), width=max(1, int(3 * s)))
    palette = " / ".join(p.upper().replace("_", " ") for p in brief.palette[:3])
    d.text((200 * s, 1650 * s), f"A MEMORY PIECE  ·  {palette}",
           font=f_tech, fill=(220, 200, 175, 170))
    d.text((190 * s, 2780 * s), f"词曲 / 编曲  {brief.artist}", font=f_small, fill=(220, 200, 175, 150))
    mode_cn = "大调" if brief.mode == "major" else "小调"
    d.text((W - 190 * s, 2780 * s),
           f"{brief.bpm:g} BPM  ·  {brief.key} {mode_cn}  ·  STEREO 48 kHz",
           font=f_tech, fill=(220, 200, 175, 145), anchor="ra")

    img.save(path)
    img.resize((1500, 1500), Image.LANCZOS).save(path.with_name("cover_1500.jpg"), quality=94)
    img.crop((0, 380, size, 2067 * size // 3000)).resize((1920, 1080), Image.LANCZOS).save(
        path.with_name("banner_1920.jpg"), quality=94)


# --------------------------------------------------------------------------
# 创作手记 PDF（Pillow 排版 → 多页 PDF）
# --------------------------------------------------------------------------
def make_notes_pdf(path: Path, brief: Brief, res: dict, cover: Path) -> None:
    W, H = 1240, 1754          # A4 @150dpi
    paper, ink, gold = (245, 236, 221), (36, 27, 19), (154, 107, 54)
    f_h = _font("C:/Windows/Fonts/STZHONGS.TTF", 46)
    f_h2 = _font("C:/Windows/Fonts/STZHONGS.TTF", 30)
    f_body = _font("C:/Windows/Fonts/Dengl.ttf", 21)
    f_small = _font("C:/Windows/Fonts/Dengl.ttf", 18)
    f_num = _font("C:/Windows/Fonts/bahnschrift.ttf", 54)

    def page():
        img = Image.new("RGB", (W, H), paper)
        return img, ImageDraw.Draw(img)

    def header(d, kicker, title):
        d.text((90, 80), kicker, font=f_small, fill=gold)
        d.text((90, 110), title, font=f_h2, fill=ink)
        d.line([(90, 168), (W - 90, 168)], fill=(196, 154, 97), width=2)

    def footer(d, n):
        d.text((90, H - 70), brief.title_en, font=f_small, fill=(139, 115, 88))
        d.text((W - 90, H - 70), f"{n} / 3", font=f_small, fill=(139, 115, 88), anchor="ra")

    pages = []

    # P1 封面
    img, d = page()
    d.rectangle([0, 0, W, 430], fill=(28, 20, 13))
    d.text((90, 70), brief.artist.upper(), font=f_small, fill=(216, 173, 114))
    d.text((W - 90, 70), "NT-003 / 2026", font=f_small, fill=(216, 173, 114), anchor="ra")
    d.text((90, 175), brief.title, font=_font("C:/Windows/Fonts/STZHONGS.TTF", 96),
           fill=(245, 234, 216))
    d.text((92, 305), brief.title_en, font=_font("C:/Windows/Fonts/georgia.ttf", 34),
           fill=(216, 173, 114))

    art = Image.open(cover).convert("RGB").resize((520, 520), Image.LANCZOS)
    img.paste(art, (90, 490))

    mode_cn = "大调" if brief.mode == "major" else "小调"
    d.text((650, 500), "创作手记", font=f_h2, fill=ink)
    d.text((650, 560), brief.style, font=f_body, fill=(87, 69, 52))
    d.text((650, 600), f"{brief.key} {mode_cn}  ·  {brief.bpm:g} BPM  ·  {brief.meter}/4",
           font=f_body, fill=(87, 69, 52))
    d.text((650, 640), f"{brief.bars} 小节  ·  {res['duration']/60:.2f} 分钟",
           font=f_body, fill=(87, 69, 52))
    d.text((650, 706), "一句话设定", font=f_small, fill=gold)
    d.multiline_text((650, 742), _wrap(brief.logline, 15), font=f_body,
                     fill=(60, 45, 32), spacing=12)

    d.text((90, 1110), "本册结构", font=f_small, fill=gold)
    toc = [("01", "情绪与结构", "分段四维 · 弧线 · 实测电平"),
           ("02", "动机与和声", "五音细胞 · 和弦骨架 · 配器时间线"),
           ("03", "音色与验证", "母带指标 · 阈值判定 · 自检四问")]
    yy = 1160
    for num, t, sub in toc:
        d.text((90, yy), num, font=_font("C:/Windows/Fonts/bahnschrift.ttf", 30), fill=gold)
        d.text((160, yy), t, font=f_body, fill=ink)
        d.text((160, yy + 34), sub, font=f_small, fill=(125, 98, 72))
        yy += 96
    d.text((90, 1560), "音乐制作固定流程 · 十阶段产物", font=f_small, fill=(139, 115, 88))
    pages.append(img)

    # P2 结构
    img, d = page()
    header(d, "01 / EMOTIONAL ARCHITECTURE", "情绪不是标签，而是一条弧线")
    y = 200
    for s in brief.sections:
        d.text((90, y), s.name, font=f_body, fill=ink)
        d.text((300, y), f"{s.bars} 小节", font=f_small, fill=(87, 69, 52))
        d.text((450, y), f"效价 {s.valence:.2f}   唤醒 {s.arousal:.2f}   "
                         f"紧张 {s.tension:.2f}   距离 {s.distance:.2f}",
               font=f_small, fill=(87, 69, 52))
        y += 44
        d.text((112, y), (s.mood or "")[:44], font=f_small, fill=(125, 98, 72))
        y += 42

    # 弧线折线
    d.text((90, 800), "情绪弧线", font=f_small, fill=gold)
    top, bottom, x0, x1 = 860, 1050, 130, W - 200
    n = max(1, len(brief.sections) - 1)

    def px(i):
        return x0 + (x1 - x0) * i / n

    def py(v):
        return bottom - (bottom - top) * v

    for label, attr, color in (("效价", "valence", (196, 154, 97)),
                               ("唤醒", "arousal", (154, 107, 54)),
                               ("距离", "distance", (116, 90, 64))):
        pts = [(px(i), py(getattr(s, attr))) for i, s in enumerate(brief.sections)]
        d.line(pts, fill=color, width=3, joint="curve")
        for p in pts:
            d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=color)
        d.text((x1 + 10, pts[-1][1] - 9), label, font=f_small, fill=color)
    for i, s in enumerate(brief.sections):
        d.text((px(i), bottom + 14), s.name[:6], font=f_small,
               fill=(139, 115, 88), anchor="ma")
    d.line([(x0, bottom + 4), (x1, bottom + 4)], fill=(196, 154, 97), width=1)

    d.text((90, 1130), "分段 RMS（实测）", font=f_small, fill=gold)
    for i, (name, v) in enumerate(res["section_rms"].items()):
        col, row = i % 3, i // 3
        d.text((90 + col * 380, 1176 + row * 40), name, font=f_body, fill=ink)
        d.text((90 + col * 380 + 210, 1176 + row * 40), f"{v:.1f} dBFS",
               font=f_body, fill=(87, 69, 52))
    footer(d, 1)
    pages.append(img)

    # P3 动机与和声
    img, d = page()
    header(d, "02 / MOTIF & HARMONY", "一个五音细胞，四次不同的说法")
    motif = brief.motif or [5, 1, 3, 2, 1]
    d.text((90, 200), "动机", font=f_small, fill=gold)
    d.text((160, 186), " – ".join(str(m) for m in motif), font=f_h, fill=ink)
    d.text((90, 262), "音级走向（1 = 主音）：第一次不进主音，句尾停在延伸音上。",
           font=f_body, fill=(87, 69, 52))

    d.text((90, 330), "和弦骨架（前 16 小节）", font=f_small, fill=gold)
    for i, ch in enumerate(res["chords"][:16]):
        col, row = i % 4, i // 4
        x = 90 + col * 262
        yy = 380 + row * 48
        d.text((x, yy), f"{i + 1:>2}", font=f_small, fill=(139, 115, 88))
        d.text((x + 42, yy - 4), chord_symbol(ch), font=f_body, fill=ink)

    d.text((90, 620), "配器时间线", font=f_small, fill=gold)
    yy = 666
    for s in brief.sections:
        inst = "、".join(s.instruments) if s.instruments else "—"
        d.text((90, yy), s.name, font=f_body, fill=ink)
        d.text((250, yy), _wrap(inst, 34).replace("\n", "  "), font=f_small,
               fill=(87, 69, 52))
        yy += 56

    d.text((90, 1040), "动机的四种说法", font=f_small, fill=gold)
    yy = 1090
    for line in ("原形：跳进后级进回落，像一句没说完的话",
                 "只改尾音：换成和弦的延伸音，同一个动机被重新解释",
                 "倒影：音序上下翻转，像记忆被重新拼接",
                 "片段：只留前三个音，让听者自己补完"):
        d.text((110, yy), "· " + line, font=f_body, fill=(60, 45, 32))
        yy += 46
    footer(d, 2)
    pages.append(img)

    # P4 音色 / 验证
    img, d = page()
    header(d, "03 / TIMBRE, SPACE & VERIFICATION", "暖色不是加空气，而是少一点高频")
    d.text((90, 196), "综合响度", font=f_body, fill=(87, 69, 52))
    d.text((90, 226), f"{res['lufs']:.1f} LUFS", font=f_num, fill=ink)
    d.text((90, 300), f"真峰 {res['true_peak']:.1f} dBFS   ·   "
                      f"相关度 {res['corr']:.2f}   ·   重心 {res['centroid']:.0f} Hz",
           font=f_body, fill=(87, 69, 52))
    y = 370
    d.text((90, y), "阈值判定", font=f_small, fill=gold)
    y += 40
    for c in res["checks"]:
        d.text((110, y), ("PASS" if c["ok"] else "FAIL"), font=f_small,
               fill=(60, 110, 70) if c["ok"] else (150, 60, 50))
        d.text((190, y), c["label"], font=f_small, fill=ink)
        d.text((720, y), c["detail"], font=f_small, fill=(87, 69, 52))
        y += 36

    y += 26
    d.text((90, y), "音色参数", font=f_small, fill=gold)
    y += 40
    for line in ("中提琴：280 / 680 / 1500 Hz 琴体共振，3.8–4.4 kHz 四阶低通，无金属模态",
                 "毛毡钢琴：180 / 560 Hz 琴体，10 条拉伸泛音，6.0 kHz 低通",
                 "音乐盒：1 / 2.76 / 5.4 / 8.93 倍模态，6.8 kHz 低通，长混响 0.38"):
        d.text((110, y), "· " + line, font=f_small, fill=(60, 45, 32))
        y += 38

    y += 26
    d.text((90, y), "自检四问", font=f_small, fill=gold)
    y += 38
    for q in ("删掉音色后，动机还成立吗？",
              "高点是否只靠响度？",
              "怀旧是否只靠噪声与低通？",
              "空间是否掩盖了主体？"):
        d.text((110, y), "· " + q, font=f_body, fill=(60, 45, 32))
        y += 40
    y += 20
    d.text((90, y), "以上为信号测量，不是听感评价；未做盲听不得声称听感已验证。",
           font=f_small, fill=(125, 98, 72))
    footer(d, 3)
    pages.append(img)

    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=150.0)

    import os
    if os.environ.get("COMPOSER_PREVIEW"):
        for i, pg in enumerate(pages, 1):
            pg.save(path.with_name(f"preview_p{i}.png"))


def _wrap(text: str, width: int) -> str:
    out, line = [], ""
    for ch in text:
        if len(line) >= width:
            out.append(line)
            line = ""
        line += ch
    out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# README
# --------------------------------------------------------------------------
def write_readme(path: Path, brief: Brief, res: dict, info: dict, files: dict) -> None:
    mins = int(res["duration"] // 60)
    secs = res["duration"] - mins * 60
    lines = [
        f"# {brief.title} / {brief.title_en}",
        "",
        f"**{brief.artist}** · {brief.style} · {brief.bpm:g} BPM"
        f"（{brief.bpm_range[0]:g}–{brief.bpm_range[1]:g}） · {brief.meter}/4 · {mins}:{secs:04.1f}",
        f"{pretty_key(brief.key)} {'大调' if brief.mode == 'major' else '小调'}"
        f" · {brief.bars} 小节 · {len(brief.sections)} 段",
        "",
        f"> {brief.logline}",
        "",
        "## 结构",
        "",
        "| 段落 | 小节 | 效价 | 唤醒 | 紧张 | 距离 |",
        "|---|---|---|---|---|---|",
    ]
    for s in brief.sections:
        lines.append(f"| {s.name} | {s.bars} | {s.valence:.2f} | {s.arousal:.2f} "
                     f"| {s.tension:.2f} | {s.distance:.2f} |")
    lines += ["", "## 母带", "",
              f"- 综合响度 **{res['lufs']:.1f} LUFS**（BS.1770 近似）",
              f"- 真峰 **{res['true_peak']:.1f} dBFS**；采样峰值 {res['peak']:.3f}",
              f"- 立体声相关 {res['corr']:.3f}；频谱重心 {res['centroid']:.0f} Hz；"
              f"{brief.sr/1000:.0f} kHz / 24-bit",
              "", "### 分段 RMS", ""]
    lines.append(" · ".join(f"{k} {v:.1f}" for k, v in res["section_rms"].items()))
    lines += ["", "## 阈值判定", ""]
    for c in res["checks"]:
        lines.append(f"- {'PASS' if c['ok'] else 'FAIL'} · {c['label']} — {c['detail']}")
    lines += ["", f"**总体：{'通过' if res['passed'] else '未通过'}**", "",
              "## 交付文件", "", "| 文件 | 说明 |", "|---|---|"]
    for name, desc in files.items():
        lines.append(f"| `{name}` | {desc} |")
    lines += ["", "## 生成方式", "",
              "```powershell",
              f"python -m composer.cli build {Path(brief.source).as_posix() if brief.source else 'brief.json'}",
              "```",
              "",
              "> MIDI 是固定 BPM 的结构草图，不含 rubato 与微时序，与音频不等价。",
              "> 以上指标为信号测量，不是听感评价。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
