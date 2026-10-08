# 固定拓扑 Sizing Agent（SKY130 两级运放示例）

[English README](README_EN.md)

给定一个已选定的拓扑，让大模型迭代调整 `.param` 尺寸，由真实 ngspice 验证：先 DC 工作点修复，再性能优化（增益、UGB、相位裕度、功耗），最后生成中英文 PDF 报告。

## 一行命令：选择模型

用 `SIZING_MODEL` 选模型（或给脚本加 `--model`），**必须指定**，否则程序拒绝启动。

| 模型名 | 后端 | 实际模型 ID | 备注 |
|---|---|---|---|
| `qwen` | 本地 GPU | Qwen3-8B | 自动选空闲 GPU、启动服务、结束后关闭 |
| `fable` | Claude Code | claude-fable-5-1 | |
| `sonnet` | Claude Code | claude-sonnet-5-5 | |
| `opus` | Claude Code | claude-opus-5-5 | |
| `astra` | Codex | gpt-6-astra | |
| `sol` | Codex | gpt-6-sol | |
| `luna` | Codex | gpt-6-luna | |

```bash
cd /home/xu/Multi-agent

# 方式一：环境变量
SIZING_MODEL=qwen   bash scripts/run_all.sh
SIZING_MODEL=sonnet bash scripts/run_all.sh
SIZING_MODEL=opus   bash scripts/run_all.sh
SIZING_MODEL=fable  bash scripts/run_all.sh
SIZING_MODEL=astra  bash scripts/run_all.sh
SIZING_MODEL=sol    bash scripts/run_all.sh
SIZING_MODEL=luna   bash scripts/run_all.sh

# 方式二：参数（等价）
bash scripts/run_all.sh --model sol

# 兼容旧写法：只指定后端，使用该后端默认模型（claude→sonnet，codex→astra，qwen→qwen）
SIZING_BACKEND=codex bash scripts/run_all.sh

# 不调用任何模型，只验证基线网表并出报告
bash scripts/run_all.sh --baseline-only
```

- 也可以直接写完整模型 ID：`SIZING_MODEL=gpt-6-sol`、`SIZING_MODEL=claude-opus-5-5`。
- 模型名与 `SIZING_BACKEND` 冲突（如 `SIZING_MODEL=sol SIZING_BACKEND=claude`）会报错。
- Claude 模型通过 Claude Code CLI 调用，使用本机 Claude Code 已登录的账号；Codex 模型通过 `codex exec` 调用，使用 VS Code 里 ChatGPT/Codex 扩展已登录的账号（`~/.codex/auth.json`），不读取你的 `config.toml`，也不会保存会话。云端模型不需要 GPU。
- 找不到 CLI 时可手动指定：`CLAUDE_BIN=/path/to/claude`、`CODEX_BIN=/path/to/codex`（默认自动查找 PATH 与 VS Code 扩展目录）。
- 某个模型账号额度用完会直接报错，例如 `claude CLI error (claude-fable-5-1): You're out of usage credits`，换一个模型名重跑即可。
- 结果里 `summary.json` 的 `design_backend` 和 `model` 字段记录这次用的模型，PDF 也会写出。
- 已运行的本地 Qwen 服务（`scripts/start.sh` 启动）可用 `SIZING_MODEL=qwen bash scripts/run_demo.sh` 复用，`stop.sh` 关闭；`run_demo.sh` 同样识别 `SIZING_MODEL`。

## 每次迭代模型看到什么

所有模型走同一个入口，输入完全一致：

1. `ANALOG_DESIGN_RULES.md`：通用公式、判据和通用诊断自检（每次调用重新读取，哈希记入 `calls.json`）。
2. `reference.spice`：电路连接、硬约束，以及“本电路专用说明”（DC 平衡关系、补偿电阻等经 ngspice 扫描标定的数据）。
3. `target.json`：规格、参数边界、DC 验收判据。
4. 本轮实测（DC 工作点、性能、具体失败项）和本次运行的迭代历史（不含模型此前的说明文字）。
5. `derived_calculations`：Python 预先算好的数值（各管 gm/Id、gm/gds，两级电流失配比 Rm 与目标 W/L，补偿电阻与零点位置，p2、UGB、A1/A2 估算，功耗余量）。由 `analog_agents/analog_calc.py` 生成，是估算，仿真实测优先。

模型只返回 JSON：`analysis` 与至多 3 个 `changes`。提案由 `apply_changes` 校验（边界、整数、匹配、拓扑文本不变、old_value 一致），不合格则记录并反馈下一轮，但仍占一次迭代。

## 流程与停止条件

1. 基线 DC 检查（Python 判据，见 `target.json → dc_acceptance`：导通、过驱动、饱和裕量、方向）。
2. DC 失败：进入 DC 修复，最多 `max_dc_iterations`（5）次；超出则以 `dc_iteration_limit` 结束。
3. DC 通过：做 AC，进入性能优化，总迭代最多 `max_iterations`（10）。
4. 全部指标满足即 `targets_passed`；否则 `max_iterations_reached`。

## 输出

结果在 `circuits/two_stage_opamp/results/`：`summary.json`（状态、迭代数、仿真数、耗时、token、模型）、`history.json`（每轮参数、测量、提案及接受/拒绝）、`calls.json`（每次模型调用的 token、规则哈希、原始响应）、`measurements.json`、`candidate.spice`、`logs/simulation_NNN.{spice,log,json}`、`final_report.pdf` 与 `final_report_zh.pdf`。每次运行前会把上一次归档到 `results/runs/`。

## 文件说明

| 路径 | 作用 |
|---|---|
| `scripts/run_all.sh` / `run_all.py` | 一行入口；解析模型；Qwen 时自动管理 GPU 服务 |
| `analog_agents/models.py` | 模型注册表（别名 → 后端 + 模型 ID） |
| `analog_agents/client.py` | `LocalClient`（Qwen）、`ClaudeCliClient`、`CodexCliClient` |
| `analog_agents/rules.py`、`context.py` | 注入全局规则；压缩输入（去重、编码设备数据、突出失败项） |
| `analog_agents/analog_calc.py` | 公式库与 `derive()`（预计算数值） |
| `agents/sizing_agent/` | prompt、提案校验与应用 |
| `simulator/` | ngspice 运行与解析、PDF 报告 |
| `circuits/two_stage_opamp/` | reference 网表、`specs/target.json`、结果 |
| `ANALOG_DESIGN_RULES.md` | 通用模拟电路公式与诊断规则（与拓扑无关） |
| `main.py` | 优化主循环 |

## 新增或修改模型

在 `analog_agents/models.py` 的 `MODELS` 里加一行 `'别名': ('claude'|'codex', '模型ID')` 即可，无需改其他文件。新增 Codex 模型前可用 `~/.codex/models_cache.json` 查看账号可用的模型名。

## 修改规则或电路说明

- 与电路无关的公式、判据、通用建议 → `ANALOG_DESIGN_RULES.md`。
- 与这个运放拓扑相关的数值、方向、标定数据 → `reference.spice` 头部的 `TOPOLOGY-SPECIFIC NOTES` 注释。
- 新电路需同步填写 `target.json` 的结构化约束（边界、`device_dimensions`、`dc_acceptance`、`topology` 里的管子角色）；只改注释不会被 Python 强制。

## 测试

```bash
/home/xu/.venv/bin/python -m pytest -q     # 55 项，不调用模型，不需要 GPU
```
