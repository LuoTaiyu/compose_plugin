# 作曲插件 · FIXED PIPELINE

把 [音乐制作固定流程](../docs/音乐制作固定流程.md) 的十个阶段做成可执行代码：
一张立项卡进去，一首带母带、MIDI、封面、创作手记与 QA 报告的作品出来。

不是采样拼贴，也不是"文本生成音频"——所有声音由代码合成，所有决定都能在代码里找到出处。

## 快速开始

```powershell
# 在仓库根目录执行（composer/ 已可直接导入）

# 校验一张立项卡
python -m composer.cli validate composer/demo/blue_hour/brief.json

# 生成一张空白立项卡
python -m composer.cli new my_song --title "无名" --title-en "UNTITLED"

# 渲染（输出到 brief.json 同级的 output/）
python -m composer.cli build composer/demo/blue_hour/brief.json
```

```powershell
python -m composer.cli build <brief.json> --out <dir> --lufs -15 --tp -2.5 --skip-pdf
```

退出码：`0` 全部阈值通过；`2` 渲染完成但有阈值未过（报告里会写明是哪几项）。

依赖：Python 3.10+、NumPy、Pillow。**scipy 可选**——没有它时用 IIR→FIR + overlap-add
等价实现，只是慢一些。

## 十个阶段落在哪

| 阶段 | 模块 | 做什么 |
|---|---|---|
| 0 立项 | `core.Brief` / `cli new` | 12 字段校验：段落小节数、和弦网格长度、避免项 ≥4、音色 ≤6 |
| 1 情绪与结构 | `core.Section` | 四维曲线写进立项卡，逐段给值 |
| 2 作曲 | `compose.py` | 和弦网格（模板或手写）+ 五音动机 + 按曲线生成旋律 |
| 3 演奏 | `render.render_viola` | 连奏判定、乐句位置漂移、句首句尾微时序、三层力度 |
| 4 音色 | `instruments.py` | 毛毡钢琴 / 加弱音器中提琴 / 音乐盒 / 弦乐 / 簧风琴，参数逐项对齐流程文档 |
| 5 工程 | `dsp.py` | 二阶节滤波、零相位 EQ、FFT 卷积；固定种子、可复现 |
| 6 混音 | `render.py` | 三级增益、通道表、短/长混响发送、房间声 |
| 7 母带 | `master.py` | EQ → tanh → 淡入淡出 → 响度归一 → 限幅收敛到真峰目标 |
| 8 验证 | `qa.py` | BS.1770 近似响度、4× 过采样真峰、分段 RMS、频段能量、相关度 + 阈值判定 |
| 9 交付 | `export.py` | WAV 24-bit、MIDI（自写 SMF）、3000² 封面、4 页 A4 手记、README、QA 报告 |

## 产物

```
output/
  <曲名>_<TITLE>_master.wav   48 kHz / 24-bit
  <曲名>_<TITLE>.mid          TPQ 480，5 轨，marker，固定 BPM
  cover_3000.png              3000×3000
  cover_1500.jpg              1500×1500
  banner_1920.jpg             1920×1080
  <曲名>_创作手记.pdf          4 页 A4
  README.md                   规格、分段、阈值判定
  qa_report.txt               完整测量
```

## 立项卡

见 `demo/blue_hour/brief.json`。关键字段：

```json
{
  "key": "Db", "mode": "major", "bpm": 60, "bpm_range": [57, 63],
  "bars": 56, "seed": 20261108,
  "motif": [3, 6, 2, 4, 3],
  "sections": [
    {"name": "Climax", "bars": 8, "valence": 0.45, "arousal": 0.55,
     "tension": 0.50, "distance": 0.60, "instruments": ["viola", "strings"]}
  ],
  "chords": ["Dbmaj9", "Ab13/C", "Bbm9", "Gbmaj7"]
}
```

- `sections[].bars` 之和必须等于 `bars`；`chords` 若给出，长度必须等于 `bars`。
- 不给 `chords` 就按段落功能模板生成——想完全控制就手写这 56 个和弦。
- `motif` 是音级数组（1=主音），生成时会做"只改尾音 / 倒影 / 逆行"三种变形。

## 验证原则

工具不会声称"好听"。它只保证：没有削波、没有 NaN、响度与真峰落在目标区间、
高点不靠响度堆出来、分段动态在合理范围。报告末尾固定写一句：

> 以上为信号测量，不是听感评价；未做盲听，不得声称听感已验证。

## 示例结果

`demo/blue_hour/`：《灰蓝时刻 / THE BLUE HOUR》，D♭ 大调、60 BPM、56 小节、3:54。

| 指标 | 实测 | 阈值 |
|---|---|---|
| 综合响度 | −15.2 LUFS | −16 ~ −14 |
| 真峰 | −2.6 dBFS | ≤ −1.0 |
| 采样峰值 | 0.740 | ≤ 0.85 |
| 立体声相关 | 0.919 | 0.85–0.95 |
| 频谱重心 | 315 Hz | 300–800 |
| B → Climax | +1.3 dB | ≤ +1.5 |

分段 RMS：Intro −26.9 / A1 −15.4 / B −13.6 / Climax −12.3 / A2 −15.7 / Coda −18.4。
渲染耗时约 70 秒（纯 NumPy 滤波，无 scipy）。

## 已知限制

- 没有人声轨。要加人声，按流程文档 6.5 节另建一条 bus，共振峰参数可参照参考实现。
- MIDI 是固定 BPM 的结构稿，不含 rubato、微时序与段落增益，和音频不等价。
- 纯 NumPy 路径下滤波是 IIR→FIR 近似，与 scipy 的 `lfilter` 有极小数值差异（不可闻）。
- 封面字体依赖 Windows 自带字库；缺失时退回微软雅黑。
- 力度分三层缓存：同一层内的力度差异不改变音色，只改变摆放增益——这是性能与表达的取舍。
- `COMPOSER_PREVIEW=1` 会额外导出 `preview_p1..4.png`，便于检查排版。
