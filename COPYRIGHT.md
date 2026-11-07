# 版权声明 / Copyright

Copyright © 2026 **LuoTaiyu**（GitHub: [@LuoTaiyu](https://github.com/LuoTaiyu)）。

本仓库的源代码、文档、示例立项卡与示例音频，除另有说明外，均由 LuoTaiyu 创作，
以 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布。
完整许可文本见 [LICENSE](LICENSE)。

## 你可以做什么

在 AGPL-3.0 条款下，你可以：

- 运行、研究、修改和分发本软件；
- 将修改后的版本用于商业或非商业目的；
- 通过计算机网络向用户提供本软件的功能——但必须按 AGPL 第 13 条向这些用户提供
  Corresponding Source（对应源代码）。

## 你必须遵守

- 保留本版权声明与许可证；
- 分发修改版本时，按 AGPL-3.0 提供完整对应源代码；
- 不得移除或规避第三方组件的版权与许可声明；
- 不得暗示原作者为你的修改版本背书。

## 关于生成物

- **你用本工具生成的音频、MIDI、封面与文档，归你所有**，可自由使用、发行与商用，
  无需向本项目支付费用或标注来源（标注是礼貌，不是义务）。
- 仓库内 `composer/demo/blue_hour/output/` 下的示例音频、封面、PDF 与文档，
  作为示例随代码一并按 AGPL-3.0 提供，可用于学习与测试，不得单独作为你的作品发行。

## 第三方组件

本项目**不打包**任何第三方代码或采样，仅在运行时依赖以下库，它们各自保留版权与许可：

| 组件 | 用途 | 许可 |
|---|---|---|
| [NumPy](https://numpy.org/) | 数组与 FFT 运算 | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | 封面与 PDF 排版 | HPND |
| [SciPy](https://scipy.org/)（可选） | 滤波加速 | BSD-3-Clause |

封面与 PDF 使用系统字体（华文中宋 / Georgia / Bahnschrift / 等线），字体本身不随仓库分发，
商用前请自行确认字体授权。

## 免责声明

本软件按“现状”提供，不附带任何明示或暗示的担保，包括但不限于适销性、
特定用途适用性与非侵权担保。作者不对使用本软件产生的任何直接或间接损失负责。

工具输出的测量结果（响度、真峰、频谱等）是**信号测量**，不是听感评价，
也不能替代母带工程师的判断。

## 如何署名

若你希望署名，可以写：

> 使用 [compose_plugin](https://github.com/LuoTaiyu/compose_plugin) 生成（AGPL-3.0）

## 联系

- Issues：<https://github.com/LuoTaiyu/compose_plugin/issues>
- 版权与授权问题：通过 GitHub Issue 联系作者
