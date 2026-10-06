# SKY130 Two-Stage Op-Amp — Qwen Automated Sizing

## 1. 当前任务

本次只实现：

**固定 Two-Stage Op-Amp 拓扑下，使用本地 Qwen 根据完整 ngspice 仿真结果进行 reasoning-based transistor sizing，并通过 SKY130 + ngspice 反复真实仿真，直到满足目标或达到最大迭代次数。**

不要实现其他未来 Agent。

---

# 2. 开始前必须检查本地项目

在修改代码前：

1. 阅读 `/home/xu/multi-agent/` 当前完整目录。
2. 阅读已有 Python 代码。
3. 查找并阅读已有本地 Qwen 调用代码。
4. 阅读 `/home/xu/multi-agent/tools_path.md`。
5. 根据本地已有代码确定 Qwen 的调用方式、模型、endpoint 和参数。
6. 尽量复用已经可以工作的 Qwen inference 方法。

不要自行假设：

- Qwen API 地址
- port
- model name
- serving framework
- inference command

不要重新部署 Qwen。

Codex 负责实现系统，但真正的 sizing reasoning 必须由本地 Qwen 完成。

---

# 3. 整理输入文件

用户开始时会直接把：

```text
/home/xu/multi-agent/reference.spice
/home/xu/multi-agent/target.json
```

放在项目根目录。

Codex 首先自动建立：

```text
/home/xu/multi-agent/circuits/two_stage_opamp/reference/
/home/xu/multi-agent/circuits/two_stage_opamp/specs/
```

然后将：

```text
/home/xu/multi-agent/reference.spice
```

移动到：

```text
/home/xu/multi-agent/circuits/two_stage_opamp/reference/reference.spice
```

将：

```text
/home/xu/multi-agent/target.json
```

移动到：

```text
/home/xu/multi-agent/circuits/two_stage_opamp/specs/target.json
```

移动后所有程序使用新的路径。

---

# 4. 清理旧结构

删除以前与当前实验冲突或已经废弃的：

- topology agent
- simulation agent
- evaluation agent
- mock simulator
- 旧 sizing agent
- 旧测试输出
- 当前任务不需要的旧 Agent 代码

不要删除：

- `.git/`
- `tools_path.md`
- 当前 prompt.md
- 用户提供的 reference.spice
- 用户提供的 target.json
- 已经可工作的本地 Qwen 调用代码

在确认输入文件已经正确移动之前，不得删除原始输入。

---

# 5. 最终项目结构

尽量整理成：

```text
multi-agent/
│
├── prompt.md
├── tools_path.md
├── main.py
│
├── agents/
│   └── sizing_agent/
│       ├── agent.py
│       └── prompt.md
│
├── circuits/
│   └── two_stage_opamp/
│       ├── reference/
│       │   └── reference.spice
│       │
│       ├── specs/
│       │   └── target.json
│       │
│       ├── working/
│       │   └── candidate.spice
│       │
│       └── results/
│           ├── current.log
│           ├── measurements.json
│           ├── history.json
│           ├── logs/
│           │   ├── simulation_001.log
│           │   ├── simulation_002.log
│           │   └── ...
│           └── final_report.pdf
│
└── simulator/
    ├── ngspice_runner.py
    └── report_generator.py
```

如果现有项目已经存在合理且等价的 Qwen interface，可以保留并复用。

不要为了匹配目录树重复实现相同功能。

---

# 6. EDA 工具

首先读取：

```text
/home/xu/multi-agent/tools_path.md
```

使用其中定义的：

- SKY130 PDK
- ngspice

禁止：

- sudo
- 重新安装 PDK
- 重新安装 ngspice
- 修改 `/home/xu/eda/`
- 使用 mock simulator

所有最终性能必须来自真实 SKY130 + ngspice 仿真。

---

# 7. Reference Circuit

固定参考电路：

```text
circuits/two_stage_opamp/reference/reference.spice
```

当前任务是：

**Sizing Optimization**

不是：

**Topology Generation**

因此不得：

- 改变运放拓扑
- 增加新的 gain stage
- 删除核心 transistor
- 将 two-stage op-amp 改成其他 topology
- 从零重新生成另一套 op-amp

---

# 8. 参数约束

reference.spice 已经通过共享 `.param` 对搜索空间进行了裁剪。

必须保持这些 matching constraints。

例如：

## Differential pair

M1 和 M2 必须使用相同：

```text
W_IN
L_IN
```

因此：

```text
W_M1 = W_M2
L_M1 = L_M2
```

Qwen 不允许分别修改 M1 和 M2。

---

## First-stage current mirror

M3 和 M4 必须使用相同：

```text
W_LOAD
L_LOAD
```

因此：

```text
W_M3 = W_M4
L_M3 = L_M4
```

Qwen 不允许破坏 current-mirror matching。

---

## Bias mirror

Bias reference transistor 和 tail transistor 使用共享的：

```text
L_BIAS
```

并通过有限数量的 sizing parameter 控制。

---

## General constraints

所有 transistor：

```text
W > 0
L > 0
```

必须满足 target.json 中定义的参数范围。

禁止 Qwen：

- 直接修改单个 matched transistor 的 W/L；
- 绕过 `.param` hard-code 某个 transistor 的尺寸；
- 修改 SKY130 device model；
- 修改 PDK；
- 改变 supply voltage；
- 改变 load capacitance；
- 改变 process corner；
- 改变 input common-mode condition。

所有优化必须通过允许的 `.param` 完成。

---

# 9. Target

读取：

```text
circuits/two_stage_opamp/specs/target.json
```

其中定义：

- simulation conditions
- performance targets
- allowed parameters
- parameter bounds
- maximum iterations

禁止在 Python 中 hard-code 这些值。

---

# 10. Simulation Runner

实现：

```text
simulator/ngspice_runner.py
```

它不是 LLM Agent。

每次 simulation 必须：

1. 调用真实 ngspice。
2. 使用 SKY130 model。
3. 保存完整 stdout/stderr/log。
4. 保存 `.meas` 结果。
5. 保存 DC operating-point diagnostics。
6. 保存 return code。
7. 给每次仿真分配独立 simulation number。

例如：

```text
simulation_001.log
simulation_002.log
simulation_003.log
```

同时：

```text
current.log
```

始终指向或复制最新一次完整 log。

不得只保存 performance summary。

---

# 11. Qwen Sizing Agent

当前唯一的设计 Agent：

```text
agents/sizing_agent/
```

必须调用本地 Qwen。

Codex 不得代替 Qwen 完成 sizing reasoning。

每轮 Qwen 至少读取：

1. `target.json`
2. `reference.spice`
3. 当前 `candidate.spice`
4. 最新完整 ngspice log
5. `measurements.json`
6. `history.json`

完整 log 是核心输入。

`measurements.json` 只是辅助摘要，不能替代 log。

---

# 12. Qwen 必须先分析 Simulation Validity

在修改 sizing 前，Qwen 首先判断：

- ngspice 是否成功；
- 是否有 convergence error；
- 是否有 warning；
- `.meas` 是否失败；
- 是否有 NaN / invalid result；
- AC analysis 是否有效。

如果 simulation 无效：

优先分析仿真或 bias 问题。

禁止看到某个 measurement 缺失后直接随机修改 W/L。

---

# 13. Qwen 必须分析 DC Operating Point

在优化 AC performance 前，必须分析 DC OP。

至少关注：

- VDD
- input common-mode
- bias node
- tail node
- first-stage output
- final output DC voltage
- supply current
- available transistor operating-point information

判断：

- differential pair 是否正常工作；
- tail source 是否正常；
- current mirror 是否正常；
- second stage 是否正常偏置；
- output 是否贴近 rail；
- 是否有 transistor cutoff；
- 是否存在明显异常 current；
- 是否存在 headroom 问题。

如果 DC OP 明显错误：

**优先修复 DC OP。**

不要直接优化 Gain/UGB/PM。

---

# 14. Qwen 再分析 AC 和 Power

DC OP 合理后分析：

- DC/open-loop gain
- UGB
- phase margin
- frequency response
- compensation
- power

Qwen 应根据完整电路状态进行 circuit-level reasoning，而不是：

```text
某指标低
→ 随机猜一个 parameter
```

---

# 15. Sizing 输出格式

要求 Qwen 返回结构化 JSON。

例如：

```json
{
  "analysis": {
    "simulation_valid": true,
    "dc_op_valid": true,
    "main_problem": "insufficient phase margin",
    "reasoning": "..."
  },
  "changes": [
    {
      "parameter": "CC",
      "old_value": "1p",
      "new_value": "1.4p",
      "reason": "..."
    }
  ]
}
```

Python 必须检查：

- JSON 合法；
- parameter 在 allowed_parameters 中；
- value 在 parameter_bounds 中；
- matching constraints 没有被破坏。

验证后才能生成新的 candidate.spice。

---

# 16. Optimization 原则

每轮优先只改变少量参数。

避免一次修改所有参数。

Qwen 应考虑 parameter 与电路性能之间的物理关系，例如：

- gm
- ro
- gain
- current density
- parasitic capacitance
- dominant pole
- non-dominant pole
- Miller compensation
- UGB
- phase margin
- power
- headroom

必须记录每次修改理由。

---

# 17. Measurements 与 Pass/Fail

普通 Python 可以从仿真结果提取：

- gain
- UGB
- phase margin
- power

并判断是否达到 target。

但这个判断只是 termination condition。

它不能替代 Qwen 对完整 log 的分析。

即使：

```text
gain / UGB / PM / power
```

全部有数值，Qwen 仍应读取完整 log。

---

# 18. History

保存：

```text
circuits/two_stage_opamp/results/history.json
```

每轮至少记录：

```text
iteration
simulation_number
parameters_before
measurements
simulation_status
qwen_analysis
parameter_changes
parameters_after
qwen_token_usage
iteration_time
```

不得覆盖以前 iteration。

---

# 19. Iteration 与 Simulation 分开计数

必须分别统计：

## Iteration Count

Qwen 完成一次：

```text
读取仿真
→ reasoning
→ sizing decision
```

记为一次 optimization iteration。

## Simulation Count

每调用一次 ngspice：

```text
simulation_count += 1
```

包括：

- reference baseline simulation
- candidate simulation
- debug/retry simulation

因此：

```text
simulation_count
```

不一定等于：

```text
iteration_count
```

最终报告必须分别给出。

---

# 20. Token 统计

记录所有 Qwen sizing calls 的 token usage。

优先使用本地 Qwen serving interface 返回的：

- prompt_tokens
- completion_tokens
- total_tokens

如果 serving framework不能直接提供 token usage，则读取本地已有 tokenizer，以与实际 Qwen 模型匹配的 tokenizer 计算输入和输出 token。

禁止凭字符串长度猜 token 数。

最终至少统计：

```text
total_prompt_tokens
total_completion_tokens
total_tokens
```

只统计当前 optimization experiment 中 Qwen Agent 的 token。

---

# 21. Optimization Time

在第一次 baseline simulation 开始前记录：

```text
optimization_start_time
```

在：

- 所有 target 达到，或
- max_iterations 达到

之后记录：

```text
optimization_end_time
```

计算：

```text
total_optimization_time_seconds
```

PDF 中同时给出容易阅读的时间格式。

---

# 22. Main Loop

`main.py` 负责：

```text
baseline reference
       ↓
ngspice
       ↓
FULL LOG
       ↓
Qwen Sizing Agent
       ↓
simulation validity reasoning
       ↓
DC OP reasoning
       ↓
AC / power reasoning
       ↓
parameter changes
       ↓
candidate.spice
       ↓
constraint validation
       ↓
ngspice
       ↓
FULL LOG
       ↓
Qwen
       ↺
```

直到：

```text
all targets passed
```

或者：

```text
max_iterations reached
```

---

# 23. 开发顺序

严格按照：

### Step 1

阅读整个 `/home/xu/multi-agent/`。

### Step 2

找到本地 Qwen 的已有调用方式。

### Step 3

移动 `reference.spice` 和 `target.json` 到规定位置。

### Step 4

整理项目目录并删除废弃 Agent。

### Step 5

直接运行 reference.spice。

### Step 6

检查完整 baseline ngspice log 和 DC OP。

如果 reference/testbench 有错误：

先修复 reference/testbench。

不要开始自动优化。

### Step 7

实现 Python ngspice runner。

### Step 8

实现 Qwen sizing interface。

### Step 9

完成：

```text
ngspice
→ full log
→ Qwen
→ sizing
→ candidate
→ ngspice
```

至少两轮。

### Step 10

确认闭环稳定后运行完整 optimization。

### Step 11

读取最终结果和 history。

### Step 12

生成最终 PDF。

---

# 24. Final PDF Report

优化结束后必须自动生成：

```text
circuits/two_stage_opamp/results/final_report.pdf
```

PDF 由确定性 Python report generator 生成，不需要增加 Report Agent。

实现：

```text
simulator/report_generator.py
```

生成 PDF 时，Codex 必须实际读取最终：

- candidate.spice
- target.json
- measurements
- history
- simulation logs
- token statistics
- timing statistics

禁止在 PDF 中填写虚构结果。

---

# 25. PDF 必须包含

## 1. Optimized Netlist

完整展示最终优化后的：

```text
candidate.spice
```

包括最终 W/L、IBIAS、CC 等。

---

## 2. Circuit Topology Diagram

根据固定 reference topology 生成清晰的电路拓扑图。

必须至少标出：

- M1/M2 differential pair
- M3/M4 current mirror
- M5 tail source
- M6 second gain stage
- M7 second-stage load
- bias circuit
- Miller compensation capacitor
- load capacitor
- VINP
- VINN
- VDD
- OUT

图必须反映实际最终 netlist。

不要使用与 netlist 不一致的示意图。

---

## 3. Circuit Performance

表格至少包含：

```text
Metric
Target
Final Result
Pass/Fail
```

包括：

- DC Gain
- UGB
- Phase Margin
- Power

同时列出：

- VDD
- temperature
- load capacitance
- process corner

---

## 4. Optimization Iterations

显示：

```text
Total Optimization Iterations
```

---

## 5. Simulation Count

显示：

```text
Total ngspice Simulations
```

---

## 6. Optimization Time

显示：

```text
Total Optimization Time
```

---

## 7. Token Usage

至少显示：

```text
Prompt Tokens
Completion Tokens
Total Tokens
```

---

# 26. PDF 可额外包含

如果容易实现，可以增加一个简洁 iteration table：

```text
Iteration
Gain
UGB
PM
Power
Modified Parameters
```

以及最终 parameter table：

```text
Parameter
Initial
Final
```

但不要因此增加新的 Agent 或大幅复杂化系统。

---

# 27. PDF 技术要求

按照当前环境可用的 PDF 生成工具实现。

优先生成清晰、可读、适合科研记录的 PDF。

如果需要 Python PDF library，先检查当前环境和已有项目依赖。

不要使用 sudo。

如果必须增加 Python dependency，优先使用当前用户环境可以安装或已经存在的方案。

---

# 28. 当前不做

不要实现：

- Temperature Sensor
- BJT Sensor
- SAR ADC
- Top-Level Architecture Agent
- Topology Selection Agent
- Compatibility Agent
- Integration Agent
- Layout Agent
- Magic automation
- LVS
- PEX
- Monte Carlo
- PVT optimization
- multi-model benchmark

当前只有一个 LLM design agent：

```text
Qwen Sizing Agent
```

---

# 29. 完成条件

只有完整实现：

```text
Reference Netlist
      ↓
SKY130/ngspice baseline
      ↓
FULL LOG
      ↓
Qwen reasoning
      ↓
Constrained sizing
      ↓
Candidate Netlist
      ↓
SKY130/ngspice
      ↓
FULL LOG
      ↓
Qwen reasoning
      ↺
      ↓
Termination
      ↓
Final PDF
```

才算完成。

完成后向用户报告：

1. 最终目录结构；
2. Qwen 调用方式；
3. baseline DC OP；
4. baseline performance；
5. 每轮 Qwen 的主要 reasoning；
6. 每轮 parameter changes；
7. 最终参数；
8. 最终 performance；
9. iteration count；
10. simulation count；
11. optimization time；
12. token usage；
13. `final_report.pdf` 的路径。

然后停止，不要自行扩展项目。