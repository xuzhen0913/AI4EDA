# SKY130 两级运放：PMOS 第二级、DC 优先尺寸优化

**一句命令完成：选择空闲 GPU → 启动本地 Qwen → DC 检查与尺寸迭代 → 性能仿真 → 生成中英文 PDF → 关闭本次服务。**

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh
```

[English README](README_EN.md)

**本次更新只完成构建和静态检查，没有运行 Qwen、GPU 或 ngspice。** `results/` 内已有报告来自旧版本电路，不代表新 PMOS 第二级的性能；下次实际运行会归档旧报告并生成新报告。

## 当前电路是什么

实际输入为 `circuits/two_stage_opamp/reference/reference.spice`。

- M1/M2：NMOS 差分输入对。
- M3/M4：完全匹配的 PMOS 电流镜有源负载，固定 1:1。
- M5：NMOS 尾电流源。
- **M7：PMOS 共源增益管**，栅极接第一级输出 `n2`，源极和体端接 VDD，漏极接 OUT。
- **M6：NMOS 偏置电流源**，栅极接 `vbias_n`，源极和体端接地，漏极接 OUT。
- MBIAS_N：二极管连接的 NMOS 偏置参考，同时为 M5、M6 提供栅压。

共 **8 个 MOS**。旧的 MBIAS_P、IBIAS_P 和 `vbias_p` 分支已删除。
`W_STAGE2/L_STAGE2` 现在控制 M7，不再控制 M6。改变 `N_STAGE2_BIAS` 则调整 M6 相对偏置参考管的宽度倍率。

## 参数与强制匹配

| 器件 | W | L |
|---|---|---|
| M1、M2 | `W_IN` | `L_IN` |
| M3、M4 | `W_LOAD` | `L_LOAD` |
| MBIAS_N | `WBN0` | `L_BIAS_N` |
| M5 | `N_TAIL*WBN0` | `L_BIAS_N` |
| M6 | `N_STAGE2_BIAS*WBN0` | `L_BIAS_N` |
| M7 | `W_STAGE2` | `L_STAGE2` |

`N_TAIL` 与 `N_STAGE2_BIAS` 必须是正整数，可取不同值；当前初始值均为 1。
W/L 以微米计。基础参数及乘积后的实际尺寸都受 `target.json` 限制：当前 M5 的 W 上限为 100 µm，M6/M7 为 200 µm。
网表强制共享表达式，Python 拒绝小数倍率、越界值、旧值不匹配和改变器件连接的提案。
旧参数 `N_STAGE2_LOAD`、`WBP0`、`L_BIAS_P` 不再允许优化；M3/M4 没有可调倍率。

无效提案不会修改电路，会记录错误并反馈下一轮，但仍占用决策额度。下次启动会从新 reference 重新生成候选，不会继续使用旧拓扑的 `working/candidate.spice`。

## DC 条件：必须按实际器件极性计算

第一步仅运行 DC OP。Python 检查全部 8 个器件，包括偏置参考管；不能仅凭模型说“DC 正常”就放行。
当前判据为：

- 电流幅值 `|Id| >= 1 nA`；
- NMOS 使用 `VGS=Vg−Vs`、`VDS=Vd−Vs`；PMOS 使用 `VSG=Vs−Vg`、`VSD=Vs−Vd`；
- 漏源方向正确，即上述 VDS/VSD 为正；
- `VGS/VSG−|Vth| >= 0`；
- `VDS/VSD−|模型 VDSAT| >= 0`。

这些阈值位于 `target.json → dc_acceptance`，属于本项目的强反型饱和验收规则。缺少诊断量、非有限值或 DC 仿真错误均不能通过。器件端子和 NFET/PFET 类型会与网表核对，避免使用旧的 DC 映射。

对新的第二级，具体为：

| 器件 | 导通条件 | 饱和／电压余量条件 |
|---|---|---|
| M6，NMOS 电流源 | `V(vbias_n)−|Vth6| >= 0` | `V(out)−|VDSAT6| >= 0` |
| M7，PMOS 增益管 | `VDD−V(n2)−|Vth7| >= 0` | `VDD−V(out)−|VDSAT7| >= 0` |

所以 OUT 过低可能使 M6 退出饱和，OUT 过高可能使 M7 退出饱和。提高 `n2` 会减小 M7 的 VSG、削弱 PMOS 导通，不能沿用 NMOS 增益管的栅压判断。
M5、M6 共用偏置参考：修改 `WBN0` 或 `L_BIAS_N` 会影响整个 NMOS 偏置网络。

## 增益、相位裕度与功耗的计算

当前 AC 输入为 VINP=+0.5、VINN=−0.5，因此差分激励为 1 V。程序显式计算：

```text
Vin_diff = V(vinp) - V(vinn)
A_diff   = V(out) / Vin_diff
Gain_dB  = 20*log10(|A_diff|)
L        = -A_diff
PM       = 180° + continuous_phase(L) × 180/π，在 UGB 处取值
Power    = -I(VSUPPLY) * V(vdd)
```

- `dc_gain_db` 是 **1 Hz 的低频增益近似**，不是独立 DC 扫描测出的增益。
- UGB 是幅值第一次向下穿越 0 dB 的频率，扫描范围仍为 1 Hz–1 GHz。
- PMOS 共源级仍然反相；按本参考的第一级连接，整体 `A_diff` 在低频仍为负，因此保留 `L=-A_diff`，不因更换 PMOS 就盲目翻转符号。
- 运行时检查 1 Hz 的 `real(L)>0`。若极性不符、测量缺失或 AC 出错，不判定性能达标；AC 错误不会被当作已通过的 DC 工作点失败。
- 此 PM 是**反馈接 VINP 的单位负反馈、开环小信号估算**。VINP/VINN 名称不等于传统运放正负输入功能；这不是任意反馈网络的回路增益测量，也不能单凭第一次交越证明多交越系统稳定。
- `cph` 输出弧度，显式乘以 `180/π`。功耗仍取真实电源电流，已自然包含删除 PMOS 偏置支路后的变化，不使用旧支路数量估算。

函数定义参考：[ngspice 官方手册](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)。上述新拓扑的极性推导和程序修改尚未经实际仿真验证。

## 迭代和停止条件

1. 检查网表、目标、匹配表达式和 DC 端子映射。
2. 执行纯 DC；任何器件不通过，则 Qwen 根据完整日志修复偏置。
3. 全部通过后，才允许同一份候选网表执行完整 OP+AC 与功耗测量。
4. 每次尺寸决策后先重新检查 DC；性能优化导致 DC 失败时立即回到 DC 修复。
5. 全部指标和 DC 条件达标后停止，或达到额度后停止并生成报告。

**DC 修复累计最多 5 次，总决策累计最多 10 次。** 返回 DC 修复不会重置 5 次额度。
第五次 DC 修复如果仍失败就停止；如果通过，可使用剩余总额度优化性能。
基准不计入决策次数；无修改或被拒绝的决策仍占用次数。一次 DC 调用和一次完整 OP+AC 调用分别计一次仿真。
DC 不通过时，AC 指标显示“未仿真”，不会沿用旧结果或填零。

## 一键脚本和 GPU 管理

脚本优先选择配置中的 GPU 3，忙时选择另一张空闲 GPU。当前空闲阈值：显存占用不超过 1024 MiB，利用率不超过 5%。无空闲 GPU 时退出，不挤掉其他进程；该检查不是集群资源预留。

正常结束、异常或 Ctrl+C 后会尝试关闭本次启动的服务。已有本项目服务时，一键脚本拒绝再次启动；可先 `bash scripts/stop.sh`，或用 `bash scripts/run_demo.sh` 复用已有服务。SIGKILL 无法保证清理。

## 文件入口和输出

| 用途 | 文件 |
|---|---|
| 一句话全自动运行 | `scripts/run_all.sh` |
| GPU 服务生命周期 | `scripts/run_all.py`、`scripts/service.py` |
| DC／性能阶段切换 | `main.py` |
| 参考网表 | `circuits/two_stage_opamp/reference/reference.spice` |
| 指标、边界、倍率、DC 映射、AC 约定 | `circuits/two_stage_opamp/specs/target.json` |
| Qwen 规则及参数校验 | `agents/sizing_agent/prompt.md`、`agent.py` |
| 仿真执行与结果解析 | `simulator/ngspice_runner.py` |
| 双语报告、整体连线图 | `simulator/report_generator.py` |
| 模型服务配置 | `config/settings.json` |

报告：`circuits/two_stage_opamp/results/final_report.pdf` 和 `final_report_zh.pdf`。
同目录保存候选快照、配置、历史、token、时间和完整仿真日志。原有结果仍属于旧电路；下次运行前会归档到 `results/runs/`，编号日志保留。
图形生成器按网表区分新 PMOS 第二级与历史 NMOS 第二级，避免把旧报告重新画成新拓扑。

Qwen 接口：`http://127.0.0.1:8003/v1`；服务名：`qwen3-8b-local`。
权重在 `models/Qwen3-8B`；Python 在 `/home/xu/.venv`；EDA 路径由 `tools_path.md` 指定。
每轮发送完整最新日志、参考与候选网表、目标、测量值和历史。超上下文窗口时明确停止，不截断日志。

## 后续可选检查（本次未执行）

仅 CPU 基准与报告，同样受 DC 放行规则约束：

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh --baseline-only
```

回归测试：

```bash
cd /home/xu/Multi-agent
source scripts/env.sh
"$PROJECT_PYTHON" -m pytest -q -p no:cacheprovider
```

本次只更新了相关测试，未执行测试或仿真。静态检查不能保证电路收敛或性能达标。
