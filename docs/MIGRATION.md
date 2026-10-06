# 项目迁移记录（2026-10-06）

项目根目录现在是 `/home/xu/Multi-agent`。

## 日常运行

```bash
cd /home/xu/Multi-agent
source scripts/activate.sh
bash scripts/start.sh
bash scripts/test_qwen.sh
bash scripts/run_demo.sh
bash scripts/stop.sh
```

GPU 默认仍为 3，端口仍为 8003。启动器不会自动选卡，发现卡忙就退出；请在确认空闲且符合实验室调度规则后修改 `config/settings.json` 的 gpu。

## 文件放在哪里

- 项目源代码：`analog_agents/`、`scripts/`、`tests/`。
- 项目配置、提示词：`config/`、`prompts/`。
- 模型：`models/Qwen3-8B/`。权重在同一文件系统直接移动，没有重新下载；文件大小和 inode 均保持。
- 日志、历史实验、报告与文档：`logs/`、`outputs/`、`docs/`、`USER_GUIDE.pdf`。
- 项目专用缓存及临时文件：`.runtime/cache/`、`.runtime/tmp/` 等。Outlines 缓存也已移入此目录，并显式设置 OUTLINES_CACHE_DIR，避免重新写入主目录下的默认缓存。
- 通用 Python 环境保留：`/home/xu/.venv`（含已安装依赖）。
- 通用 Python 解释器、uv 及解释器链接保留：`/home/xu/.runtime/python`、`/home/xu/.runtime/tools`、`/home/xu/.runtime/bin`。

没有修改系统 Python、NVIDIA 驱动、shell 启动文件或其他用户文件。没有创建指向旧项目目录的兼容链接。uv 缓存原有 160 个绝对链接已改为迁移后缓存内的相对链接。

## 路径修改

`scripts/env.sh` 从自身位置推导 PROJECT_ROOT，并集中定义 PROJECT_VENV、PROJECT_PYTHON 和 PROJECT_UV 指向保留的通用工具。启动、停止、实验、API 测试、激活和安装脚本都使用这些变量。

`analog_agents/config.py` 原本按源码所在位置计算 ROOT，因此无需硬编码替换；模型路径依旧是相对项目根目录的 models/Qwen3-8B。新运行会把日志与结果写到新根目录。

`audit_paths.py` 将共享工具路径作为明确白名单检查，其余项目写入路径仍必须在新根目录内。主目录不是任意路径越界的豁免。

## 实际验证

- 9 项测试通过，含原有 7 项与新增的两项迁移回归测试。
- 从 `/home/xu` 通过完整路径激活环境成功；Python 导入的项目 ROOT 为 `/home/xu/Multi-agent`。
- 完整离线工作流通过：测试用固定模型响应，真实执行编排、参数更新、Mock 工具、JSON 保存和 PDF 排版。它不是 GPU 模型推理，不计入真实设计实验。
- pip 与 uv 的依赖检查通过；Python 源码语法与 Bash 入口语法检查通过。
- 模型文件大小/inode 检查通过；迁移后的路径与符号链接审计通过。
- 已实际执行新位置的 `scripts/start.sh`。GPU 3 当时已占用 26100 MiB、利用率 100%，启动器安全拒绝，未创建模型进程。
- 检查时四张 GPU 均有任务，因此迁移后的真实 Qwen 加载和模型端到端推理尚未通过验证。等待空闲后按上方日常命令运行。

详情见 `logs/migration_validation.json`、`logs/migration_tests.log`、`logs/migration_start_attempt.log` 和 `logs/migration_manifest.json`。

## 历史文档与报告

历史 PDF、实验 JSON 和验证日志中的 `/home/xu/...` 路径保留为原始运行证据，没有批量篡改历史内容。文件现在可在新目录下的相同相对位置找到。

`USER_GUIDE.pdf` 是 2026-10-02 的代码快照，使用时以本迁移说明及当前 README 的命令为准。旧逐行手册的生成程序仍有源码指纹保护：源码已更新，它会要求重新审核说明，而不是用旧行号生成误导性文档。这是迁移前就存在的版本差异，不要通过仅修改指纹绕过检查。实验 `REPORT.pdf` 的自动生成不依赖该旧手册生成器。
