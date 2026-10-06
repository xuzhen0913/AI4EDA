# 本地 Qwen + 模拟电路 Multi-Agent

项目根目录为 `/home/xu/Multi-agent`。中文手册见 [USER_GUIDE.pdf](USER_GUIDE.pdf)。

```bash
cd /home/xu/Multi-agent
source scripts/activate.sh
bash scripts/start.sh
bash scripts/test_qwen.sh
bash scripts/run_demo.sh
bash scripts/stop.sh
```

服务使用配置指定的单张 GPU，启动前检查忙碌阈值，不自动寻找空闲卡。目前配置为 GPU 3、`127.0.0.1:8003`。配置集中在 `config/settings.json`；角色提示词在 `prompts/`。

每个 Agent 真实调用本地 Qwen3-8B。电路仿真为 **MOCK 合成指标**，不是 SPICE；没有工艺 PDK，网表未执行，不能据此认定电路性能。

每次实验最终输出 `outputs/时间戳/REPORT.pdf`，包含拓扑结构图、选择理由、成功率、性能、仿真次数、迭代次数、token 和时间成本。原始统计保存在同目录 `calls.json` 与 `summary.json`。指标定义见 [报告说明](docs/REPORTING.md)。

`USER_GUIDE.pdf` 与 `logs/verification.json` 是 2026-10-02 旧版快照。新增报告模块、共享计量客户端和 GPU/端口设置以当前代码及报告说明为准；旧手册逐行附录不代表本次更新后的源码，生成器会阻止用旧解释覆盖新代码。

```bash
# 离线单元测试
python -m pytest -q --basetemp="$TMPDIR/pytest"
# 服务启动后，分别测试四个 Agent
python scripts/test_agents.py
# 检查项目缓存/临时路径与符号链接
python scripts/audit_paths.py
# 实验 PDF 在 run_demo.sh 结束时自动生成，无需单独调用模型
# 在项目内安装固定版本环境和下载模型（需要联网）
bash scripts/install.sh
```

架构：`analog_agents/client.py` 统一 API；`agents.py` 定义角色与 JSON Schema；`simulation.py` 提供工具接口与 Mock 后端；`run.py` 编排、验证、应用建议并重新评估。

`requirements.txt` 记录主要版本，`requirements.lock` 固定全部实际依赖。`scripts/env.sh` 集中设置缓存和临时目录；不要修改系统 Python、驱动或用户 shell 配置。没有在用户主目录初始化 Git 仓库。

迁移说明与测试结果见 [MIGRATION.md](docs/MIGRATION.md)。通用 Python 环境仍为 `/home/xu/.venv`，解释器和 uv 在 `/home/xu/.runtime`；项目缓存、模型、代码及新产物均在本目录。
