# SKY130 两级运放：DC 优先尺寸优化

**一行命令：自动选择空闲 GPU → 启动 Qwen → 尺寸优化 → 生成中英文 PDF → 释放本次 GPU 服务。**

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh
```

[English README](README_EN.md)

## 运行前需要知道

项目使用已有的本地 Qwen3-8B、vLLM、SKY130 和 ngspice，不会重新安装模型或修改 `/home/xu/eda`。
脚本优先选配置中的 GPU 3；如果忙，则选择另一张空闲 GPU。判定空闲的条件为显存占用不超过 1024 MiB、利用率不超过 5%。没有空闲 GPU 时退出，不杀死其他人的进程。
此检查不是集群资源预留；共享服务器仍应遵守管理员的调度规则。

本脚本启动的模型服务在正常完成、Python 异常或 Ctrl+C 后会尝试关闭；不会关闭已有的其他服务。
如果本项目的 Qwen 已经启动，一键脚本会提示退出；可运行 `bash scripts/run_demo.sh` 复用它，或先运行 `bash scripts/stop.sh`。
进程被系统强制杀死（例如 SIGKILL）时无法保证执行清理。

报告位于：

- 中文：`circuits/two_stage_opamp/results/final_report_zh.pdf`
- 英文：`circuits/two_stage_opamp/results/final_report.pdf`

达到迭代上限也会生成报告。流程跑完不等于电路达标。DC 没通过时，报告把 AC 指标标为“未仿真”，不会填零或沿用上一轮的结果。

## 写死在网表中的匹配约束

实际参考文件：`circuits/two_stage_opamp/reference/reference.spice`。

| 器件 | W 表达式 | L 表达式 |
|---|---|---|
| M1、M2 | `W_IN` | `L_IN` |
| M3（二极管连接） | `W_LOAD` | `L_LOAD` |
| M4 | `N_LOAD*W_LOAD` | `L_LOAD` |
| MBIAS_N（二极管连接） | `WBN0` | `L_BIAS_N` |
| M5 | `N_TAIL*WBN0` | `L_BIAS_N` |
| MBIAS_P（二极管连接） | `WBP0` | `L_BIAS_P` |
| M7 | `N_STAGE2_LOAD*WBP0` | `L_BIAS_P` |
| M6 | `W_STAGE2` | `L_STAGE2` |

三个 N 必须是正整数，初始值分别为 1、1、2。`N=1` 是合法的 1:1 电流镜。
只有 Python 校验通过后才写入新的候选电路，不能通过修改单管 W/L 绕过约束。
无效或旧值不匹配的提案被拒绝并反馈给下一轮；保留当前尺寸，这次决策仍占用迭代额度。
除基础参数范围外，程序还检查 `N×W` 乘积：M4、M5 的 W 最大 100 µm，M7 最大 200 µm，实际边界以 target.json 为准。
ngspice 的 `.param` 本身不限制整数类型，所以“共享关系”由网表强制，“整数性和边界”由 Python 强制。

注意：为了让 M7 与 MBIAS_P 的 L 一致，M7 初始 L 从旧参考的 0.5 µm 改为共享的 1.0 µm。因此旧实验性能不能当作新参考的 baseline。
`reference.original.spice` 仅保留最初用户输入，不作为当前运行入口。

## DC 检查和迭代逻辑

1. 读取 `target.json` 和固定参考网表，校验匹配关系及参数范围。
2. 只调用一次 DC OP 仿真；执行网表中 `.control` 内的 `op`，移除标记的 AC 分析块。
3. 检查全部九个 MOS（包括两个偏置参考管）的工作点。必须满足：
   - 漏源电压方向正确；
   - `|Id| >= 1 nA`；
   - NMOS 的 `VGS-|Vth| >= 0`、PMOS 的 `VSG-|Vth| >= 0`；
   - NMOS 的 `VDS-|VDSAT| >= 0`、PMOS 的 `VSD-|VDSAT| >= 0`。
4. 任一器件不通过或数据缺失：不给 AC 放行；Qwen 根据完整日志和失败器件信息调整尺寸。
5. 全部通过才执行完整 OP + AC 仿真，提取增益、UGB、相位裕度及功耗，并进行性能优化。
6. 每次模型尺寸决策之后，先重新检查 DC；通过才执行完整性能仿真。后续 DC 失败时立即回到 DC 修复。
7. 全部性能达标则停止，否则到预算上限停止并生成报告。

**DC 修复决策累计最多 5 次，全部决策累计最多 10 次。** 后续返回 DC 修复也占用同一个 5 次额度，不重置。
DC 第五次修复后如果仍失败，就停止；如果通过，剩余总额度可以用于性能优化。
基准仿真不算一次模型迭代。一次模型读取日志并给出决定算一次迭代，即使没有改参数。
一次 DC 调用和一次完整 OP+AC 调用分别计一次仿真，所以仿真次数可能大于迭代次数。

这是本项目的强反型饱和验收规则，阈值可在 `target.json` 的 `dc_acceptance` 中调整。使用模型报告的 `VDSAT`，不拿长沟道近似 `VGS-Vth` 代替。
来源：[ngspice 官方手册](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)。模型参数是连续的，边界验收不等于验证全部模拟设计要求。

## 修改哪些文件

| 目的 | 文件 |
|---|---|
| 指标、参数边界、整数倍率、DC 阈值和迭代额度 | `circuits/two_stage_opamp/specs/target.json` |
| 固定电路、共享参数和测量语句 | `circuits/two_stage_opamp/reference/reference.spice` |
| Qwen 设计规则 | `agents/sizing_agent/prompt.md` |
| 数值与结构约束检查 | `agents/sizing_agent/agent.py` |
| DC 判据、真实 ngspice 调用 | `simulator/ngspice_runner.py` |
| DC／性能阶段切换和计数 | `main.py` |
| 模型、端口、GPU 首选项、上下文窗口 | `config/settings.json` |
| GPU 选择与服务生命周期 | `scripts/service.py`、`scripts/run_all.py` |
| PDF 内容和整体连线图 | `simulator/report_generator.py` |

现有接口是 `http://127.0.0.1:8003/v1`，模型服务名 `qwen3-8b-local`。请求包括 target、参考网表、候选网表、完整最新日志、测量摘要和全部迭代历史。超出上下文窗口会明确中断，不会静默截断日志。

## 文件与依赖位置

- `main.py`：优化入口；`scripts/run_all.sh`：推荐的一键入口。
- `analog_agents/`：保留的 Qwen 客户端与配置读取模块，当前只有 sizing 一个设计 Agent。
- `models/Qwen3-8B/`：模型权重；`.runtime/`：本项目缓存与临时文件。
- `/home/xu/.venv/`：共用 Python 环境；`tools_path.md`：已有 EDA 工具的绝对路径。
- `working/candidate.spice`：当前候选；`results/`：报告、JSON、完整日志及每次实际执行的网表。
- `results/runs/`：后续运行前归档的旧报告和摘要；`results/logs/`：不覆盖的编号仿真日志。

## 不使用 GPU 的检查

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh --baseline-only
```

这也遵循 DC 放行规则并生成中英文报告，但不调用 Qwen，不证明优化闭环已完成。

```bash
cd /home/xu/Multi-agent
source scripts/env.sh
"$PROJECT_PYTHON" -m pytest -q -p no:cacheprovider
```

单元测试中的固定输入仅测试参数校验、阶段切换及计数，不代表实际电路仿真或模型推理。
