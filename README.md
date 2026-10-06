# Alpha Preflight

透明素材交付前，先看看边缘。

检查贴纸、图标和切图是否真的透明，把它们放到深浅背景上对比，再导出一份离线报告。可以独立运行，也可以作为 Codex Skill 使用。核心处理在本地完成，只依赖 Python 和 Pillow。

[English](README.en.md) · [Skill](skills/alpha-preflight/SKILL.md) · [检查规则](skills/alpha-preflight/references/interpretation.md)

![真实生成的报告页面，切换到深色背景](docs/report-preview.jpg)

## 运行

需要 Python 3.10 或更新版本。在项目目录中运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/alpha-preflight/requirements.txt
.venv/bin/python skills/alpha-preflight/scripts/inspect_alpha.py ./images --out ./report
```

将 `./images` 换成你的图片或文件夹。运行完成后直接打开 `report/index.html`；测量数据保存在 `report/report.json`。Windows 中使用 `.venv\Scripts\python.exe` 代替 `.venv/bin/python`。

也可以一次传入多个文件：

```sh
.venv/bin/python skills/alpha-preflight/scripts/inspect_alpha.py "logo.png" "sticker.webp" --out ./report-2
```

每次使用新的报告目录。原图只读，已有报告不会被覆盖。

## 报告能告诉你什么

| 检查 | 结果的含义 |
| --- | --- |
| 真实透明度 | 统计完全透明、半透明和不透明像素；有 Alpha 通道不等于存在透明像素 |
| 内容范围 | 给出可见内容的边界、四边留白，以及是否碰到画布边缘 |
| 深浅底预览 | 在棋盘格、白色、深色、赭色背景间切换，全图与像素细节一起看 |
| 软边提示 | 标出需要目测的亮色或暗色中性边缘；有意设计的描边也可能触发 |
| 可疑棋盘格 | 检查不透明图片角落的重复灰度图案；是否为假透明仍需判断 |
| 输入异常 | 损坏文件、动画和不支持的输入单独列出，不影响其他文件的报告 |

“未见自动提示”只代表这些检查没有命中，不是质量合格证明。检测不到的彩色光晕、硬白边、头发细节等仍应目测。工具不自动抠图、去白边或修改素材。

## 作为 Skill 使用

将 `skills/alpha-preflight` 文件夹安装到你的技能目录，例如：

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R -n skills/alpha-preflight "${CODEX_HOME:-$HOME/.codex}/skills/"
```

重新加载 Skills，然后提供图片路径或上传图片，发送：

```text
$alpha-preflight 检查这些 PNG 是否真的透明，并生成深浅底预览报告。
```

Skill 的脚本、依赖清单、检查解释和许可证都在同一个文件夹内。其他支持 `SKILL.md`、本地 Python 和文件预览的宿主也能使用这套工作流。没有本地执行能力的宿主需要另外提供运行环境。

## 看一个可复现的例子

[报告 HTML](docs/demo/index.html)和[测量 JSON](docs/demo/report.json)均已包含在仓库里；下载后打开 HTML。示例素材是脚本绘制的测试图，包括真正透明、全不透明 Alpha、画进去的棋盘格、亮色软边、碰边和全透明六种情形。它们不含用户私人素材。

重新生成样例和报告：

```sh
.venv/bin/python examples/make_samples.py ./new-samples
.venv/bin/python skills/alpha-preflight/scripts/inspect_alpha.py ./new-samples --out ./new-demo
.venv/bin/python -m unittest discover -s tests -v
```

## 范围

支持静态 8-bit PNG、WebP 和 JPEG，识别 PNG 索引色透明及透明色键。每份报告最多 100 张图，每张最多 4000 万像素；文件夹递归扫描，跳过隐藏目录和符号链接。动画与 16-bit PNG 会报错，不会悄悄只检查第一帧或降低位深。

预览按 8-bit sRGB 输出，可读的内嵌色彩配置会转换；无配置时假定为 sRGB。原文件不变。报告预览移除原始元数据，但仍包含可见图片，分享前应确认素材适合公开。

退出码：正常报告为 `0`；输入或写入错误为 `1`。加入 `--fail-on-review` 后，存在待复核提示且无输入错误时返回 `2`；参数错误同样返回 `2`，不生成报告。

## 贡献

最有帮助的反馈是一张可以公开的失败样例、预期行为与实际报告。尤其欢迎漏检、误报和色彩配置的复现。检查规则应能解释和验证，不添加不透明的综合“质量评分”。代码、文档和示例采用 [MIT 许可证](LICENSE)。
