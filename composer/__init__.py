"""固定流程作曲工具（FIXED PIPELINE）。

把《音乐制作固定流程》的十个阶段变成可执行代码：
立项卡 → 情绪与结构 → 作曲 → 演奏 → 音色 → 工程 → 混音 → 母带 → 验证 → 交付。
"""
__version__ = "0.1.0"

from .core import Brief, load_brief  # noqa: F401
