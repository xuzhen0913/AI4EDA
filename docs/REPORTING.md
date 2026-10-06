# 实验 PDF 输出（2026-10-05）

运行方式不变：先 `bash scripts/start.sh`，再 `bash scripts/run_demo.sh`，用完执行 `bash scripts/stop.sh`。最终 PDF 位于本次 `outputs/时间戳/REPORT.pdf`。此次为避开忙碌的 GPU 0、1、2，配置改为 GPU 3 和端口 8003；以后仍需按实际资源占用选择卡号。

`analog_agents/reporting.py` 新增确定性的 ReportingAgent，直接使用 ReportLab 绘制与概念网表对应的 MOS 拓扑图、排版 Architecture Agent 的理由及实测统计。不调用本地模型或外部 GPT，不需要 API 密钥，也不会编造性能数字。

指标口径：

- **Success rate**：本次单次实验中，流程正常完成且最终 Mock 评估全部达标为 1/1，否则为 0/1。不是多次独立实验的统计成功率。另列通过 JSON 校验的 API 调用成功率；真实电路成功率为 N/A。
- **Circuit performances**：最后一次完成的 Mock 评估，列目标、结果和逐项判断。不是历史最优，也不是真实 SPICE。
- **Number of simulations**：分别列真实 SPICE 次数（当前 0）、Mock 尝试次数和完成次数。op/ac/tran 计划不计为已执行仿真。
- **Number of iterations**：实际应用优化建议作为下一轮输入的次数，初始评估不计。相同参数再次应用也计一轮。
- **Token cost**：累计每次 vLLM 响应的 prompt/completion/total token。包含无效输出已经消耗的已知 token；无 usage 的失败请求标为缺失，合计为已知下限。SDK 自动重试关闭。无云端账单，但硬件、电费未计量，货币成本 N/A。
- **Time cost**：从主流程开始到计算结束，另列 API 与 Mock 工具耗时。不包含服务启动、最终 PDF/汇总写盘、服务停止。报告排版本身不耗 LLM token；开发这套程序的 Codex 会话不计入实验。

调用链增加：`run.py` 创建共享 `LocalClient` → 四个 Agent 调用同一客户端并标注角色名 → 客户端保存每次请求的真实 usage、耗时、校验状态 → 主循环统计工具次数与实际参数更新次数 → `summarize()` 汇总 → `ReportingAgent.run()` 自动生成 PDF。

异常处理：主循环失败时保存 failure.json，并在 finally 中尽量保存 calls.json、summary.json 和失败报告，随后保持失败退出。配置读取/输出目录初始化等更早的失败，以及报告生成自身失败，不保证能生成 PDF。无响应的数据不补造。

本次增加 `tests/test_reporting.py` 检查用量缺失、Schema 失败但保留 usage、成功率定义及无结果失败报告。测试记录位于 logs/report_tests.log。

旧版 USER_GUIDE.pdf 是历史快照，逐行说明不含新增模块。不要只更新旧手册源码哈希绕过检查；如重新制作完整手册，应同步审核并改写逐行解释。
