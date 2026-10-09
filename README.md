# 三 Agent 运放设计流程（SKY130）：拓扑选择 → 尺寸优化 → 性能审核

[English README](README_EN.md)

给定规格（`circuits/opamp/specs/target.json`）和一个 reference 电路库（`circuits/opamp/reference/`，共 6 种运放结构），
由三个互相独立、与具体电路无关的 Agent 协作，用真实 ngspice 仿真闭环完成设计，最后生成中英文 PDF 报告。

## 三个 Agent 与流程

| Agent | 目录 | 职责 | 输入（每项只出现一次） |
|---|---|---|---|
| 拓扑选择 | `agents/topology_agent/` | 按规格从候选结构中选一个 | 指标、testbench 说明、各 reference 的 **profile**（优缺点描述）；返工时还有此前各轮摘要与审核意见 |
| 尺寸优化 | `agents/sizing_agent/` | 只改被选中电路的可调 `.param`，先 DC 后性能 | 指标与预算、当前网表（含该电路的专用说明）、最新实测（合并后的器件表、节点电压）、预计算数值、本次迭代历史、全局公式手册；返工时还有审核意见 |
| 性能审核 | `agents/review_agent/` | 判断是否达标；不达标则判定是拓扑问题还是尺寸问题，并写修改意见 | Python 逐项指标对比、被选 profile、最终器件表/节点电压/参数（含贴边界标记）、sizing 每一步的改动与结果、日志中无法由结构化数据表达的部分 |

整个流程**只有这三个 Agent**，没有“每个 reference 一个专用 sizing agent”。三个 Agent 的 prompt、代码、公式手册里**没有任何具体电路的信息**
（器件名、参数名、拓扑名）；唯一含具体拓扑信息的地方是 `circuits/opamp/reference/*.spice`（`tests/test_references.py` 用正则强制检查这一点）。

```
specs + 全部 reference 的 profile
        │
        ▼
 ┌────────────────┐   选中的 reference
 │ 拓扑选择 Agent │ ───────────────┐
 └────────────────┘                ▼
        ▲                 ┌────────────────┐  DC≤5 次，总决策≤10 次（每次 sizing）
        │ fail_topology   │ 尺寸优化 Agent │  先 DC 修复，再性能优化，全部由真实 ngspice 验证
        │ + 修改意见      └────────────────┘
        │                         │ 最终网表 + 日志 + 历史 + 实测
        │                         ▼
        │                 ┌────────────────┐
        └──────────────── │ 性能审核 Agent │ ── pass ──► 结束，输出 PDF
              fail_sizing └────────────────┘
              + 修改意见 ──► 回到尺寸优化 Agent（本轮不再重选拓扑）
```

- **整体流程最多 3 轮**（`target.json → budgets.max_rounds`，要求 1…3）。一轮 = （需要时）选拓扑 → 一次完整 sizing → 审核。
- **每次 sizing** 仍遵循原来的次数：先 DC，DC 修复累计最多 5 次（`max_dc_iterations`）；DC 通过后做性能优化，该次 sizing 总决策最多 10 次（`max_iterations`）。
  两种预算相互独立：流程 3 轮，每轮的 sizing 都可以用满 10 次，所以整个流程里 sizing 决策可以超过 3 次（最多 30 次）。
- 第 1 轮必选拓扑。之后：审核判 `fail_topology` → 下一轮重新选拓扑（已被判失败的拓扑不再提供），sizing 从新 reference 的初始值开始；
  审核判 `fail_sizing` → 下一轮拓扑不变，sizing 带着审核意见继续（默认从上一轮最终网表继续；审核认为该网表比初始更差时可设 `restart_sizing_from_reference` 从 reference 重来）。
- 审核结论以 Python 的逐项数值对比为准：审核 Agent 若说 `pass` 但有指标不达标，会被改判 `fail_sizing` 并在 `review.json` 记录；
  审核 Agent 若判 `fail_*`，必须给出非空的修改意见。
- 三轮结束仍未通过则 `max_rounds_reached`，报告里照实记录每一轮。

## 一行命令：选择模型

用 `SIZING_MODEL` 选模型（或给脚本加 `--model`），**必须指定**，否则程序拒绝启动。三个 Agent 使用同一个模型，但各有独立的客户端，token 与调用分别记录。

| 模型名 | 后端 | 实际模型 ID | 备注 |
|---|---|---|---|
| `qwen` | 本地 GPU | Qwen3-8B | 自动选空闲 GPU、启动服务、结束后关闭；上下文仅 32k |
| `fable` | Claude Code | claude-fable-5-1 | |
| `sonnet` | Claude Code | claude-sonnet-5-5 | |
| `opus` | Claude Code | claude-opus-5-5 | |
| `astra` | Codex | gpt-6-astra | |
| `sol` | Codex | gpt-6-sol | |
| `luna` | Codex | gpt-6-luna | |

```bash
cd /home/xu/Multi-agent

SIZING_MODEL=sonnet bash scripts/run_all.sh        # 完整三 Agent 流程
bash scripts/run_all.sh --model sol                # 等价写法

# 不调用任何模型：只仿真某一个 reference 的初始网表并出报告（检查 reference 能否被工具链读懂）
bash scripts/run_all.sh --baseline-only --reference two_stage_nmos_input_pmos_stage2
```

- 也可以直接写完整模型 ID：`SIZING_MODEL=gpt-6-sol`、`SIZING_MODEL=claude-opus-5-5`；旧的 `SIZING_BACKEND=qwen|claude|codex` 仍可用（选该后端默认模型）。
- Claude 模型通过 Claude Code CLI 调用（本机已登录账号）；Codex 模型通过 `codex exec` 调用（`~/.codex/auth.json`），不读 `config.toml`，不保存会话。找不到 CLI 时用 `CLAUDE_BIN` / `CODEX_BIN` 指定。
- 某个模型账号额度用完会直接报错，换一个模型名重跑即可。
- 已运行的本地 Qwen 服务（`scripts/start.sh`）可用 `SIZING_MODEL=qwen bash scripts/run_demo.sh` 复用，`stop.sh` 关闭。

## reference 库（唯一含具体拓扑信息的地方）

`circuits/opamp/reference/` 每个文件是一种候选结构，文件名即 id，统一为“结构_输入管极性[_第二级]”：

| 文件（id） | 结构 |
|---|---|
| `two_stage_nmos_input_pmos_stage2` | 两级 Miller 运放，NMOS 输入，PMOS 共源第二级（**已验证**可达标） |
| `two_stage_pmos_input_nmos_stage2` | 两级 Miller 运放，PMOS 输入，NMOS 共源第二级（未验证） |
| `folded_cascode_nmos_input` | 折叠式共源共栅，NMOS 输入（未验证） |
| `folded_cascode_pmos_input` | 折叠式共源共栅，PMOS 输入（未验证） |
| `telescopic_cascode_nmos_input` | 套筒式共源共栅，NMOS 输入（未验证） |
| `telescopic_cascode_pmos_input` | 套筒式共源共栅，PMOS 输入（未验证） |

reference 里**只有被测电路本身**，从上到下依次是：

1. **`@profile-begin … @profile-end`**：结构、优点、缺点、适用/不适用场景、验证状态（含基线仿真观察）。拓扑选择 Agent 只能依据这段文字做选择，审核 Agent 也读它。
2. **`@analyses-begin … @analyses-end`**（可选）：JSON 列表，声明该结构适用的预计算类型（电流平衡比、补偿零极点、cascode 堆栈输出电阻与增益估计），器件名只在这里出现。
3. **NOTES 注释**：该电路专用的 DC 平衡关系、偏置关系、标定数据（sizing Agent 读）。
4. **`.param` 与电路**。可调参数就是带 `; tune 下限..上限 [单位] [int]` 注解的 `.param` 行（例：`.param W_IN=10 ; tune 1..100 um`，`int` 表示整数），其余 `.param` 为固定常数。
   器件端点、模型、W/L 表达式、DC 检查要用的诊断名都**直接从网表解析**，不再另写一遍。

**不在 reference 里的东西**（重复输入已删除）：供电/输入源/负载电容、`.lib`/`.temp`、DC 诊断 `print`、AC 分析与测量都由共享 testbench（`simulator/testbench.py`）
按 `target.json` 和电路自己的器件/节点生成，所以所有拓扑用完全相同的方式测量，改条件只改 `target.json` 一处。
reference 因此必须用端口节点 `vdd`、`vinp`、`vinn`、`out`，且不得含 `.lib/.temp/.control/.end`、`VSUPPLY/VINP/VINN/CLOAD_OUT` 与参数 `VDD/VCM/CLOAD`（加载时检查，违反即拒绝启动）。
加载时还检查：每行一个 `.param`；初值在可调范围内；整数参数的初值是整数；每个可调参数都被电路用到；`@analyses` 里的器件都存在。
有效 W/L（含 `N_TAIL*WBN0` 这类乘积）的上下限是工艺规则，放在 `target.json → device_limits`，对所有 MOS 生效。

**新增一个拓扑**：复制一个 reference，改电路、profile、注解和 NOTES，文件名按上面的规则取；不需要改任何其他文件，`pytest` 会检查它。
`target.json` 只放规格：工艺/条件、指标、器件尺寸限制、DC 判据阈值、AC 扫描、预算。

## 每次调用 Agent 看到什么

只有尺寸优化 Agent 每次调用都会读取 `ANALOG_DESIGN_RULES.md`（与电路无关的公式、判据和通用诊断自检；哈希记入调用记录）。
同一个事实只出现一次：

- **器件表**：每个 MOS 一行，合并了工作点（极性归一化的 |Vgs|、|Vds|、|Vth|、|Vdsat|）、过驱动/饱和裕量、gm、gm/Id、gm/gds、W/L 和失败的 DC 判据；不再另给“原始诊断 + DC 验收明细 + 预计算”三份。
- **参数**：值、范围、整数标记都在带注解的 `.param` 行上，不另给参数表/当前值/边界表。
- **日志**：数值行、横幅、已进结构化字段的错误/警告都不重复，只给其余行（通常为空）。
- **历史**：每次决策的改动与实测结果；不含模型此前的说明文字；最后一条的结果就是当前实测，不重复。
- **Testbench**：由代码生成的一段说明（条件与指标定义），与实际仿真网表同源。
- 拓扑选择与审核 Agent 不接收公式手册。

输出：拓扑选择 Agent 返回选中 id、每个候选的适配度与理由、预期风险；
尺寸优化 Agent 只返回 `analysis` 与至多 3 个 `changes`（提案由 `apply_changes` 校验：可调参数、范围、整数、有效 W/L 范围、网表其余文本不变、old_value 一致；不合格则记录并反馈下一轮，仍占一次迭代）；
审核 Agent 返回 `verdict`、`diagnosis`、给出错一方的 `revision_advice`、是否从 reference 重新开始。

## 输出

`circuits/opamp/results/`（每次运行前，上一次的结果整体**移入** `results/runs/<时间戳>/`）：

```
summary.json              流程状态、轮数、各 Agent 的调用数与 token、仿真数、耗时、模型、每轮摘要、最终网表路径
specs.json                本次运行用的规格
round_01/ round_02/ …     每轮一个目录
    topology_selection.json  本轮选拓扑的结果（排名、理由、风险）；沿用拓扑的轮次没有此文件
    topology_calls.json      拓扑 Agent 的调用记录
    candidate.spice          本轮的电路（sizing 过程中就地修改，结束时即最终网表）
    history.json             每次决策：分析、改动、是否接受、实测结果（第一条含起点 before）
    sizing_calls.json        尺寸优化 Agent 的调用记录（token、规则哈希、原始响应）
    summary.json             本轮 sizing 汇总（含 reference 初值）
    review.json / review_calls.json   审核结论、诊断、修改意见
    logs/simulation_NNN.{spice,log,json}   每次仿真的完整网表、日志、解析记录
final_report.pdf          英文报告
final_report_zh.pdf       中文报告
```

PDF 报告包含：最终结果与规格对比、流程各轮表、拓扑选择理由与排名、最终电路的 profile 与由网表解析出的连线表、DC 验收、参数范围/初值/终值、
每轮 sizing 的逐次迭代、审核结论与修改意见、token/仿真/耗时统计、完整 DC 诊断与最终网表。模型生成的文字保留英文原文。
（报告与拓扑无关，用网表解析的连线表代替原来针对单一电路手绘的原理图。）

## 文件说明

| 路径 | 作用 |
|---|---|
| `main.py` | 三 Agent 流程编排：轮次、返工路由、结果落盘、报告 |
| `agents/topology_agent/` | 拓扑选择 Agent（prompt、候选枚举与选择校验） |
| `agents/sizing_agent/` | 尺寸优化 Agent（prompt、提案校验与应用、输入构造；`loop.py` 为单次 sizing 循环） |
| `agents/review_agent/` | 性能审核 Agent（prompt、指标对比、输入构造、判定一致性校验） |
| `analog_agents/reference.py` | reference 库加载与检查，由网表合成 sizing 用的 target |
| `analog_agents/spice.py` | SPICE 文本工具：数值、`.param`、MOS 实例、节点、受限表达式 |
| `analog_agents/evidence.py` | 给 Agent 的实测视图（器件表、节点电压、日志去重） |
| `analog_agents/analog_calc.py` | 公式库与 `derive()`（预计算数值，按 reference 的 `@analyses` 启用） |
| `analog_agents/models.py`、`factory.py`、`client.py`、`rules.py`、`schema.py`、`config.py` | 模型注册表；每个 Agent 的客户端；Qwen/Claude/Codex 适配；公式手册注入；JSON schema 工具；本地服务配置 |
| `simulator/testbench.py` | 共享 testbench：生成完整仿真网表、描述 |
| `simulator/ngspice_runner.py` | ngspice 运行与解析、DC 检查 |
| `simulator/report_generator.py` | 中英文 PDF 报告（拓扑无关） |
| `circuits/opamp/` | `reference/`（拓扑库）、`specs/target.json`（规格）、`results/`（运行结果，已 gitignore） |
| `ANALOG_DESIGN_RULES.md` | 通用模拟电路公式与诊断规则（与拓扑无关） |
| `tools_path.md` | ngspice 与 SKY130 库路径 |
| `scripts/` | 一行入口 `run_all.sh`、复用已启动 Qwen 服务的 `run_demo.sh`、本地 Qwen 服务的安装/启停 |

## 修改规则或电路说明

- 与电路无关的公式、判据、通用建议 → `ANALOG_DESIGN_RULES.md`。
- 某个拓扑的优缺点、适用场景 → 该 reference 的 `@profile` 段；与该拓扑相关的数值、方向、标定数据 → 其 NOTES；
  可调参数及范围 → 其 `.param` 注解；预计算类型 → 其 `@analyses`。
- 工作条件、指标、预算、器件尺寸限制、AC 扫描 → `target.json`；测量定义 → `simulator/testbench.py`。

## 测试

```bash
/home/xu/.venv/bin/python -m pytest -q     # 不调用模型，不需要 GPU
```

包括：每个 reference 自洽性与命名规范、“具体电路信息只出现在 reference 中”的正则检查、恰好三个 Agent 的检查、
testbench 生成（所有 reference 同一套测量、条件只来自规格）、证据视图去重，
以及用脚本化 Agent 与脚本化仿真器测试整个流程的路由（首轮通过、sizing 返工、拓扑返工并排除失败拓扑、3 轮上限、预算校验、审核结论被数值覆盖、从头/续做、旧结果归档）。

## 已知限制

- 除 `two_stage_nmos_input_pmos_stage2` 外，其余 5 个 reference 的初始尺寸/偏置是示意性的，基线都不能通过 DC 检查（profile 里已写明）。
  折叠/套筒式使用理想偏置电压源，参数多且耦合强，5 次 DC 修复内能否通过取决于模型；这正是审核 Agent 判 `fail_topology/fail_sizing` 的依据。
- reference 不再是可以直接交给 ngspice 的完整网表（testbench 由工具生成）。想看某次实际仿真的完整网表，打开 `round_NN/logs/simulation_NNN.spice`。
