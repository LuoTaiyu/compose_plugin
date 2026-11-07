# 用户使用指南

本指南面向“想用它做一首曲子”和“想改它”的两类人。
流程背后的道理在 [音乐制作固定流程](docs/音乐制作固定流程.md)，这里只讲怎么用。

---

## 1. 它能做什么、不能做什么

**能**：给你一张立项卡，生成一首 3–5 分钟的器乐小品——母带、多轨 MIDI、封面、4 页创作手记、
QA 报告，一次跑完。

**不能**：

- 不能写歌词、不能唱。人声轨尚未实现（扩展方法见第 9 节）。
- 不能保证“好听”。它保证的是工程指标：不削波、响度与真峰达标、高点不靠音量。
- 不能替代编曲判断。和弦模板与旋律规则是起点，不是答案。
- MIDI 是固定 BPM 的结构稿，不含 rubato 与微时序，和音频不等价。

---

## 2. 环境准备

| 项 | 要求 |
|---|---|
| Python | 3.10 或更高 |
| 必需依赖 | `numpy`、`Pillow` |
| 可选依赖 | `scipy`（有则更快，无则自动回退） |
| 磁盘 | 每首曲子约 70 MB（48 kHz / 24-bit 母带） |
| 系统 | Windows / macOS / Linux 均可；封面字体在 Windows 上效果最好 |

```powershell
git clone https://github.com/LuoTaiyu/compose_plugin.git
cd compose_plugin
python -m pip install -r requirements.txt
```

验证安装：

```powershell
python -m composer.cli validate composer/demo/blue_hour/brief.json
# OK  灰蓝时刻 / THE BLUE HOUR · 56 小节 · 6 段 · 调性 Db major
```

---

## 3. 五分钟上手

```powershell
# 1) 复制一份示例立项卡，改成你自己的
python -m composer.cli new my_song --title "我的曲子" --title-en "MY SONG"

# 2) 用编辑器打开 my_song/brief.json，改标题、调性、段落、动机
#    改完先校验，错误会直接告诉你哪一项不合法
python -m composer.cli validate my_song/brief.json

# 3) 渲染（约 1–2 分钟）
python -m composer.cli build my_song/brief.json

# 4) 打开产物目录
explorer my_song\output
```

产物：

```
my_song/output/
  我的曲子_MY_SONG_master.wav    48 kHz / 24-bit 母带
  我的曲子_MY_SONG.mid           TPQ 480，5 轨，带段落 marker
  cover_3000.png                 3000×3000 封面
  cover_1500.jpg                 1500×1500 分发封面
  banner_1920.jpg                1920×1080 横幅
  我的曲子_创作手记.pdf           4 页 A4
  README.md                      规格与阈值判定
  qa_report.txt                  完整测量
```

---

## 4. 立项卡字段

立项卡是唯一的输入。12 个必填字段，缺一项 `validate` 就会报错。

| 字段 | 类型 | 说明 | 示例 |
|---|---|---|---|
| `title` | 字符串 | 中文曲名（封面逐字排版，2–4 字最好看） | `"灰蓝时刻"` |
| `title_en` | 字符串 | 英文名，全大写 | `"THE BLUE HOUR"` |
| `artist` | 字符串 | 艺人名 | `"NEON TIDE"` |
| `logline` | 字符串 | 一句话设定，必须写成“不是 A，而是 B” | `"不是要回到那一天，而是承认那天已经变成了光。"` |
| `style` | 字符串 | 风格标签，两个以内 | `"记忆小品 / Ambient Neoclassical"` |
| `key` | 字符串 | 调名，用 `b`/`#` | `"Db"`、`"F#"` |
| `mode` | `major` / `minor` | 调式 | `"major"` |
| `bpm` | 数字 | 标称速度 | `60` |
| `bpm_range` | `[低, 高]` | 弹性速度范围，决定 rubato | `[57, 63]` |
| `meter` | 整数 | 拍号分子（当前实现按 4 拍处理段落） | `4` |
| `bars` | 整数 | 总小节数 | `56` |
| `sections` | 数组 | 段落，见下 | — |
| `palette` | 字符串数组 | 核心音色，最多 6 件，写在封面副标题 | `["MUTED VIOLA", "FELT PIANO", ...]` |
| `avoid` | 字符串数组 | 避免项，**至少 4 条**，必须是具体反例 | `["不要鼓组", "不要爆发的强音"]` |
| `seed` | 整数 | 随机种子，决定旋律细节与抖动 | `20261108` |
| `tail` | 数字 | 尾音秒数，默认 7.0 | `7.0` |
| `sample_rate` | 整数 | 采样率，默认 48000 | `48000` |
| `motif` | 整数数组，可选 | 动机音级（1 = 主音），默认 `[5,1,3,2,1]` | `[3, 6, 2, 4, 3]` |
| `chords` | 字符串数组，可选 | 手写和弦网格；给了就必须等于 `bars` 长度 | `["Dbmaj9", "Ab13/C", ...]` |

### 段落对象

```json
{
  "name": "Climax",
  "bars": 8,
  "valence": 0.45,
  "arousal": 0.55,
  "tension": 0.50,
  "distance": 0.60,
  "mood": "音区最高，但不爆发，仍无鼓组",
  "instruments": ["viola", "strings", "harmonium", "piano"]
}
```

- `bars` 之和必须等于顶层 `bars`；
- 四维取值 0–1：`valence` 明暗、`arousal` 能量、`tension` 紧张、`distance` 距离；
- `arousal` 直接决定琶音密度（2/4/6/8 音每小节）与旋律音区；
- `name` 含 `intro` / `climax` / `coda` 时会套用对应的段落增益与配器规则；
- `instrument` 键当前只影响文档与封面文案，实际编制由 `name` 与段落规则决定。

### 和弦写法

支持：`maj9` `maj7` `maj` `m9` `m7` `m6` `13` `9` `sus4` `6`，斜杠低音 `Ab13/C`。
不给 `chords` 就按段落功能模板生成：`I – V/3 – vi – IV`、`ii – V – I – Vsus4` 等，
段落不同、模板池不同，climax 会在第四小节插入 `IVm`。

---

## 5. 命令参考

| 命令 | 作用 |
|---|---|
| `python -m composer.cli validate <brief.json>` | 只校验立项卡，不渲染 |
| `python -m composer.cli build <brief.json> [选项]` | 渲染 → 母带 → 验证 → 交付 |
| `python -m composer.cli new <目录> --title 中文名 [--title-en EN] [--artist 名字]` | 生成空白立项卡 |

`build` 选项：

| 选项 | 默认 | 说明 |
|---|---|---|
| `--out <目录>` | `brief.json` 同级 `output/` | 产物目录 |
| `--lufs <值>` | `-15.0` | 目标综合响度 |
| `--tp <值>` | `-2.5` | 目标真峰（dBFS） |
| `--skip-pdf` | 关 | 跳过 4 页 PDF（排版较慢） |

退出码：`0` 全部阈值通过；`2` 渲染成功但有阈值未过，看 `qa_report.txt`。

---

## 6. 读懂 QA 报告

`qa_report.txt` 分三块：基础测量、分段电平、阈值判定。

| 指标 | 含义 | 本项目的区间 |
|---|---|---|
| 综合响度 | BS.1770 近似的 K 加权响度 | −16 ~ −14 LUFS |
| 真峰 | 4× 过采样后的峰值，比采样峰值更接近编码后失真风险 | ≤ −1.0 dBFS |
| 采样峰值 | 实际样本最大值 | ≤ 0.85 |
| 立体声相关 | 左右声道相关系数，越高越“单声道” | 0.85–0.95 |
| 频谱重心 | 能量重心，越低越暖、越暗 | 300–800 Hz |
| 高点段 RMS | 高潮与前一段的电平差 | ≤ +1.5 dB |
| 中段上行跳变 | 除 intro 外每个上行段落跳变 | ≤ +2.0 dB |

**判定失败时怎么办**（按优先级）：

1. **响度不在区间**：先看真峰是否被限幅器压住。若两者冲突，说明素材峰均比过高，应减一层配器或降低 `arousal`，而不是继续推限幅。
2. **上行跳变过大**（例如 A1→B 差 4 dB）：多半是某个乐器在 B 段突然变密。按 `音乐制作固定流程` 附录 B 的做法，改琶音密度与 bus 增益，不要靠整体压限。
3. **相关度 > 0.95**：声源太居中。检查 `palette` 里是否有需要展开的层，或把混响发送调宽。
4. **重心 < 300 Hz**：低频过重。检查和弦低音是否落在 C2 附近，或降低钢琴低架。
5. **真峰 > −1**：响度归一化后再压 1–2 dB，或降低 `--lufs` 目标。

---

## 7. 常见问题

**控制台中文乱码？**
Windows 终端默认 GBK。程序已强制 UTF-8 输出；若仍乱码，先执行 `chcp 65001`。

**运行时报字体缺失 / 封面文字变成方块？**
封面优先使用 `STZHONGS.TTF`（华文中宋）、`georgia.ttf`、`bahnschrift.ttf` 等 Windows 字体，
缺失时退回微软雅黑。Linux 上请把中文字体装到系统字体目录，或改写 `export._font()` 的路径。

**内存不够 / 被系统杀掉？**
一首 4 分钟的曲子峰值约 300 MB。可降低 `sample_rate` 到 32000（产物也是 32 kHz，需自行重采样到 48 kHz）。

**太慢？**
装 scipy 会明显加快滤波与卷积：`python -m pip install scipy`。不装也能跑，只是慢 2–3 倍。

**想改音色？**
`instruments.py` 里每件乐器是一个函数，参数就是文档第 6 节的参数卡。改完重渲染即可。
不要改 `dsp.py` 的接口，否则混音与母带链会一起失效。

**想换成自己写的和弦？**
在立项卡里加 `chords` 数组，长度必须等于 `bars`。写错长度，`validate` 会直接报错。

**想让人声进来？**
目前没有。做法：新建一条 bus，用共振峰合成（三个共振峰 + 气声 + 延迟颤音），
再按第 6.5 节接一条人声通道。工程量约等于现有 `instruments.py` 的一个乐器。

**想让曲子更长？**
加大 `bars` 与各段 `bars`，同时保持段落比例。注意渲染时间与内存近似线性增长。

---

## 8. 复现与版本

- 同一 `seed` + 同一份代码 → 逐样本一致的结果（除浮点库版本差异外）。
- 建议固定依赖版本：`numpy==2.3.*`、`pillow==12.*`。
- 每次改代码后重新跑 `validate` 与 `build`，对比 `qa_report.txt` 的数值，而不是凭听感判断“有没有变”。

---

## 9. 二次开发

| 想加什么 | 改哪里 |
|---|---|
| 新乐器 | `instruments.py` 加函数，`render.py` 加一条 bus 与通道表项 |
| 新段落功能模板 | `compose.TEMPLATES` 加模板，`_template_for()` 加匹配规则 |
| 新的动机变形 | `compose._phrase_variant()` 加分支 |
| 新的验收阈值 | `qa.evaluate()` 加 `chk(...)`，同步更新本文第 6 节 |
| 新的交付格式 | `export.py` 加函数，`cli.cmd_build()` 里调用并登记到 `files` |

改阈值要同步改文档。文档与代码里的数字对不上，是这类项目最常见的问题。

---

## 10. 术语表

| 术语 | 含义 |
|---|---|
| LUFS | 感知响度单位，流媒体通常归一化到 −14 ~ −16 |
| 真峰 (True Peak) | 过采样估计的峰值，比采样峰值更接近编码后的实际峰值 |
| LRA | 响度范围，衡量动态保留程度 |
| 频谱重心 | 能量的频率重心，越低越暗 |
| 立体声相关 | 左右声道相关度，1 表示完全相同 |
| 段落增益 | 每个段落的整体电平系数，与音符力度、bus 增益相乘 |
| 五音动机 | 五个音构成的细胞，全曲重复与变形的基础 |
