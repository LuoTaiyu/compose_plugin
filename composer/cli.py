"""命令行入口：校验立项卡 → 渲染 → 母带 → 验证 → 交付。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import export, master as master_mod, qa, render
from .core import Brief, Timeline, load_brief


def _fmt_time(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def cmd_validate(args) -> int:
    brief = load_brief(args.brief)
    print(f"OK  {brief.title} / {brief.title_en} · {brief.bars} 小节 · "
          f"{len(brief.sections)} 段 · 调性 {brief.key} {brief.mode}")
    return 0


def cmd_build(args) -> int:
    t0 = time.time()
    brief = load_brief(args.brief)
    out = Path(args.out) if args.out else Path(args.brief).parent / "output"
    out.mkdir(parents=True, exist_ok=True)
    slug = brief.title_en.upper().replace(" ", "_")

    print(f"《{brief.title}》 {brief.bars} 小节 · {brief.key} {brief.mode} · {brief.bpm:g} BPM")
    mix, meta = render.render_song(brief, log=lambda s: print(s, flush=True))
    tl: Timeline = meta["timeline"]

    print("  mastering...", flush=True)
    audio, info = master_mod.master(mix, brief.sr,
                                    target_lufs=args.lufs,
                                    target_tp=args.tp)
    del mix

    print("  verifying...", flush=True)
    res = qa.evaluate(brief, audio, tl)
    res["chords"] = meta["chords"]
    (out / "qa_report.txt").write_text(qa.format_report(res, brief), encoding="utf-8")

    print("  exporting...", flush=True)
    wav = out / f"{brief.title}_{slug}_master.wav"
    export.write_wav24(wav, audio, brief.sr)
    export.write_midi(out / f"{brief.title}_{slug}.mid", brief, meta["chords"],
                      meta["melody"], tl)
    cover = out / "cover_3000.png"
    export.make_cover(cover, brief)

    if not args.skip_pdf:
        export.make_notes_pdf(out / f"{brief.title}_创作手记.pdf", brief, res, cover)

    files = {
        wav.name: f"{brief.sr/1000:.0f} kHz / 24-bit 母带",
        f"{brief.title}_{slug}.mid": "结构草图（固定 BPM，TPQ 480）",
        "cover_3000.png": "3000×3000 封面",
        "cover_1500.jpg": "1500×1500 分发封面",
        "banner_1920.jpg": "1920×1080 横幅",
        "qa_report.txt": "客观测量与阈值判定",
    }
    if not args.skip_pdf:
        files[f"{brief.title}_创作手记.pdf"] = "4 页 A4 创作手记"
    export.write_readme(out / "README.md", brief, res, info, files)

    print()
    print(f"  时长      {_fmt_time(res['duration'])}")
    print(f"  响度      {res['lufs']:.1f} LUFS   真峰 {res['true_peak']:.1f} dBFS")
    print(f"  相关度    {res['corr']:.3f}      重心 {res['centroid']:.0f} Hz")
    fails = [c for c in res["checks"] if not c["ok"]]
    print(f"  阈值      {'全部通过' if not fails else f'{len(fails)} 项未过'}")
    for c in fails:
        print(f"    FAIL {c['label']} — {c['detail']}")
    print(f"  输出      {out}  ({time.time() - t0:.1f}s)")
    return 0 if res["passed"] else 2


def cmd_new(args) -> int:
    dest = Path(args.dir)
    dest.mkdir(parents=True, exist_ok=True)
    brief = {
        "title": args.title,
        "title_en": args.title_en,
        "artist": args.artist,
        "logline": "不是______，而是______。",
        "style": "记忆小品 / Ambient Neoclassical",
        "key": "Db",
        "mode": "major",
        "bpm": 60,
        "bpm_range": [57, 63],
        "meter": 4,
        "bars": 48,
        "tail": 7.0,
        "sample_rate": 48000,
        "seed": 20261108,
        "palette": ["MUTED VIOLA", "FELT PIANO", "MUSIC BOX", "STRINGS", "HARMONIUM", "ROOM"],
        "avoid": ["不要鼓组", "不要爆发的强音", "不要刺耳金属余响", "不要满混响"],
        "motif": [5, 1, 3, 2, 1],
        "sections": [
            {"name": "Intro", "bars": 8, "valence": .30, "arousal": .15,
             "tension": .25, "distance": .30, "mood": "房间声与动机碎片",
             "instruments": ["room", "piano"]},
            {"name": "A1", "bars": 16, "valence": .40, "arousal": .28,
             "tension": .32, "distance": .40, "mood": "主题第一次完整出现",
             "instruments": ["viola", "piano", "music box"]},
            {"name": "B", "bars": 12, "valence": .50, "arousal": .40,
             "tension": .42, "distance": .55, "mood": "弦乐打开空间",
             "instruments": ["viola", "strings", "harmonium"]},
            {"name": "Climax", "bars": 8, "valence": .45, "arousal": .55,
             "tension": .50, "distance": .60, "mood": "唯一高点，不爆发",
             "instruments": ["viola", "strings", "piano"]},
            {"name": "Coda", "bars": 4, "valence": .25, "arousal": .12,
             "tension": .55, "distance": .55, "mood": "未完全解决",
             "instruments": ["piano", "music box"]},
        ],
    }
    p = dest / "brief.json"
    p.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {p}；编辑后运行：python -m composer.cli build {p}")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="composer", description="固定流程作曲工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="按立项卡渲染一首完整作品")
    b.add_argument("brief")
    b.add_argument("--out", default=None)
    b.add_argument("--lufs", type=float, default=-15.0)
    b.add_argument("--tp", type=float, default=-2.5)
    b.add_argument("--skip-pdf", action="store_true")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("validate", help="只校验立项卡")
    v.add_argument("brief")
    v.set_defaults(func=cmd_validate)

    n = sub.add_parser("new", help="生成一张空白立项卡")
    n.add_argument("dir")
    n.add_argument("--title", required=True)
    n.add_argument("--title-en", default="UNTITLED")
    n.add_argument("--artist", default="NEON TIDE")
    n.set_defaults(func=cmd_new)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
